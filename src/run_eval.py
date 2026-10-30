"""Run one real-API evaluation scenario and export a markdown case record.

The script never decides which tool to call. It only supplies a user request,
runs the existing ReActAgent, and records what actually happened.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import ReActAgent
from .llm import DeepSeekLLM
from .tools import TOOLS

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT / "examples"
DRAFTS_PATH = ROOT / "data" / "drafts.json"
MAX_STEPS = 8

SCENARIOS: dict[str, dict[str, str]] = {
    "normal": {
        "title": "正常排期",
        "input": "素材 M01 就按 19:00-19:30 排，我已经确认这个时段，帮我保存草稿",
    },
    "conflict": {
        "title": "时段冲突",
        "input": "素材 M01 需要排 18:00 发布，帮我处理一下",
    },
    "duplicate": {
        "title": "重复提交",
        "input": "素材 M01 就按 19:00-19:30 排，我已经确认这个时段，帮我保存草稿",
    },
    "missing": {
        "title": "素材信息不足",
        "input": "素材 M02 需要排期，帮我看看",
    },
    "rule": {
        "title": "规则风险",
        "input": "素材 M03 需要排 18:00 发布",
    },
    "save_fail": {
        "title": "保存失败",
        "input": "素材 M04 排 19:00，帮我保存",
    },
}

ACCEPTANCE_POINTS = {
    "normal": "AC-01",
    "conflict": "AC-05 / AC-11",
    "duplicate": "AC-08",
    "missing": "AC-02",
    "rule": "AC-03",
    "save_fail": "AC-09",
}


def backup_drafts() -> bytes | None:
    """Remember existing drafts so an evaluation run does not destroy user data."""

    if not DRAFTS_PATH.exists():
        return None
    return DRAFTS_PATH.read_bytes()


def restore_drafts(payload: bytes | None) -> None:
    if payload is None:
        DRAFTS_PATH.unlink(missing_ok=True)
        return
    DRAFTS_PATH.write_bytes(payload)


def reset_drafts() -> None:
    """Isolate each scenario so duplicate/first-save results are unambiguous."""

    DRAFTS_PATH.unlink(missing_ok=True)


def read_drafts() -> list[dict[str, Any]]:
    if not DRAFTS_PATH.exists():
        return []
    try:
        payload = json.loads(DRAFTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def run_once(llm: DeepSeekLLM, user_input: str) -> dict[str, Any]:
    agent = ReActAgent(llm=llm, tools=TOOLS, max_steps=MAX_STEPS)
    result = agent.run(user_input)
    return {
        "result": result,
        "trace": [dict(entry) for entry in agent.trace],
        "observations": extract_observations(agent.messages),
    }


def extract_observations(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair assistant tool calls with their tool observations."""

    calls: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                raw_arguments = function.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    arguments = {}
                calls[str(call.get("id", ""))] = {
                    "name": function.get("name"),
                    "arguments": arguments,
                }
        elif role == "tool":
            call = calls.get(str(message.get("tool_call_id", "")), {})
            content = str(message.get("content", ""))
            try:
                parsed: Any = json.loads(content)
            except json.JSONDecodeError:
                parsed = None
            observations.append(
                {
                    "name": call.get("name"),
                    "arguments": call.get("arguments") or {},
                    "result": parsed,
                    "raw": content,
                }
            )

    return observations


def run_status(run: dict[str, Any]) -> tuple[str, str, bool]:
    result = run["result"]
    if isinstance(result, dict):
        return (
            str(result.get("status", "unfinished")),
            str(result.get("reason", "unknown")),
            False,
        )
    return "finished", "final_answer", True


def final_text(run: dict[str, Any]) -> str:
    result = run["result"]
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


def tool_names(run: dict[str, Any]) -> list[str]:
    return [
        str(entry["tool"])
        for entry in run["trace"]
        if entry.get("tool")
    ]


def max_step(run: dict[str, Any]) -> int:
    steps = [int(entry.get("step", 0)) for entry in run["trace"]]
    return max(steps, default=0)


def obs(run: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [item for item in run["observations"] if item.get("name") == name]


def last_obs(run: dict[str, Any], name: str) -> dict[str, Any] | None:
    items = obs(run, name)
    return items[-1] if items else None


def obs_data(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    result = item.get("result")
    if isinstance(result, dict) and isinstance(result.get("data"), dict):
        return result["data"]
    return {}


def obs_success(item: dict[str, Any] | None) -> bool:
    if not item:
        return False
    result = item.get("result")
    return isinstance(result, dict) and result.get("success") is True


def obs_message(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    result = item.get("result")
    if isinstance(result, dict):
        return str(result.get("message", ""))
    return str(item.get("raw", ""))


def has_any(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>").replace("\r", "")


def fenced(text: str) -> list[str]:
    fence = "````" if "```" in text else "```"
    return [f"{fence}text", text, fence]


def render_trace(trace: list[dict[str, Any]]) -> list[str]:
    if not trace:
        return ["_无 trace。_", ""]

    lines = [
        "| step | tool | arguments | result_summary | next_action |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in trace:
        arguments = entry.get("arguments") or {}
        lines.append(
            "| {step} | {tool} | {arguments} | {summary} | {next_action} |".format(
                step=cell(entry.get("step", "")),
                tool=cell(entry.get("tool") or "-"),
                arguments=cell(
                    json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
                ),
                summary=cell(entry.get("result_summary", "")),
                next_action=cell(entry.get("next_action", "")),
            )
        )
    lines.append("")
    return lines


def render_export_status(
    runs: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
    scenario: str,
) -> list[str]:
    lines: list[str] = []
    for index, run in enumerate(runs, 1):
        status, reason, is_final = run_status(run)
        prefix = f"第 {index} 次：" if len(runs) > 1 else ""
        tools = " → ".join(tool_names(run)) or "无"
        lines.append(
            f"- {prefix}运行状态 `{status}`，结束原因 `{reason}`，"
            f"trace {max_step(run)} 步，工具顺序：{tools}。"
        )
    lines.append(f"- 草稿文件：`data/drafts.json`，当前 {len(drafts)} 条。")
    lines.append(f"- 导出文件：`examples/case_{scenario}.md`。")
    return lines


def evaluate(
    scenario: str,
    runs: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    run = runs[0]
    final = final_text(run)
    rows: list[dict[str, str]] = []

    if scenario == "normal":
        read = last_obs(run, "read_material")
        read_data = obs_data(read)
        check = last_obs(run, "check_rules")
        check_data = obs_data(check)
        query = last_obs(run, "query_slots")
        query_data = obs_data(query)
        save = last_obs(run, "save_draft")
        save_data = obs_data(save)

        read_ok = obs_success(read) and read_data.get("material_id") == "M01"
        check_ok = (
            obs_success(check)
            and check_data.get("passed") is True
            and check_data.get("risk_level") == "ok"
        )
        query_ok = (
            obs_success(query)
            and "19:00-19:30" in (query_data.get("available_slots") or [])
        )
        save_ok = (
            obs_success(save)
            and bool(save_data.get("draft_id"))
            and save_data.get("duplicate") is False
        )
        final_ok = has_any(final, "保存", "草稿", "排期", "已安排")

        rows.append(
            {
                "point": "AC-01 正常素材 + 空闲时段",
                "verdict": "命中" if read_ok and check_ok and query_ok and save_ok else "未命中",
                "evidence": (
                    f"read={read_ok}, check={check_ok}, query={query_ok}, "
                    f"save={save_ok}, draft_id={save_data.get('draft_id')!r}, "
                    f"final_feedback={final_ok}"
                ),
            }
        )

    elif scenario == "missing":
        read = last_obs(run, "read_material")
        data = obs_data(read)
        missing = set(data.get("missing_fields") or [])
        read_ok = obs_success(read) and {"owner", "category"}.issubset(missing)
        no_save = not obs(run, "save_draft")
        final_ok = has_any(
            final, "补充", "缺少", "缺失", "owner", "category", "提供"
        )
        rows.append(
            {
                "point": "AC-02 缺少审核所需字段",
                "verdict": "命中" if read_ok and no_save and final_ok else "未命中",
                "evidence": (
                    f"missing_fields={sorted(missing)}, no_save={no_save}, "
                    f"final_feedback={final_ok}"
                ),
            }
        )

    elif scenario == "rule":
        check = last_obs(run, "check_rules")
        data = obs_data(check)
        reasons = " ".join(str(item) for item in (data.get("risk_reasons") or []))
        risk_ok = (
            obs_success(check)
            and data.get("risk_level") == "block"
            and has_any(reasons, "100%", "治愈", "绝对化")
        )
        no_save = not obs(run, "save_draft")
        final_ok = has_any(
            final,
            "风险",
            "绝对化",
            "100%",
            "治愈",
            "不能",
            "不建议",
            "人工",
            "拦截",
        )
        rows.append(
            {
                "point": "AC-03 规则风险拦截",
                "verdict": "命中" if risk_ok and no_save and final_ok else "未命中",
                "evidence": (
                    f"risk_level={data.get('risk_level')!r}, reasons={reasons!r}, "
                    f"no_save={no_save}, final_feedback={final_ok}"
                ),
            }
        )

    elif scenario == "conflict":
        queries = obs(run, "query_slots")
        alternative_found = any(
            (obs_data(item).get("available_slots") or []) for item in queries
        )
        no_save = not obs(run, "save_draft")
        final_ok = has_any(
            final,
            "确认",
            "是否",
            "需要您",
            "要不要",
            "可以排",
            "替代",
            "18:30",
            "已被占",
            "被占用",
            "冲突",
        )
        rows.append(
            {
                "point": "AC-05 时段冲突",
                "verdict": (
                    "命中"
                    if queries and alternative_found and no_save and final_ok
                    else "未命中"
                ),
                "evidence": (
                    f"query_calls={len(queries)}, alternative_found={alternative_found}, "
                    f"no_save={no_save}, final_feedback={final_ok}"
                ),
            }
        )
        rows.append(
            {
                "point": "AC-11 硬性发布要求保护",
                "verdict": "命中" if no_save else "未命中",
                "evidence": f"no_save={no_save}（未在用户确认前改期保存）",
            }
        )

    elif scenario == "duplicate":
        first_save = last_obs(runs[0], "save_draft")
        second_save = last_obs(runs[1], "save_draft")
        first_data = obs_data(first_save)
        second_data = obs_data(second_save)
        first_ok = (
            obs_success(first_save)
            and bool(first_data.get("draft_id"))
            and first_data.get("duplicate") is False
        )
        second_ok = (
            obs_success(second_save)
            and second_data.get("duplicate") is True
            and second_data.get("draft_id") == first_data.get("draft_id")
        )
        final2_ok = has_any(
            final_text(runs[1]), "重复", "已存在", "同一", "未新增", "沿用", "一份"
        )
        rows.append(
            {
                "point": "AC-08 相同素材 + 相同最终时段重复提交",
                "verdict": (
                    "命中"
                    if first_ok and second_ok and len(drafts) == 1 and final2_ok
                    else "未命中"
                ),
                "evidence": (
                    f"first_duplicate={first_data.get('duplicate')!r}, "
                    f"second_duplicate={second_data.get('duplicate')!r}, "
                    f"same_draft_id={second_data.get('draft_id') == first_data.get('draft_id')}, "
                    f"draft_count={len(drafts)}, final_feedback={final2_ok}"
                ),
            }
        )

    elif scenario == "save_fail":
        save = last_obs(run, "save_draft")
        message = obs_message(save)
        save_failed = (
            save is not None
            and isinstance(save.get("result"), dict)
            and save["result"].get("success") is False
            and "草稿存储服务暂不可用" in message
        )
        final_ok = has_any(
            final, "失败", "不可用", "未保存", "没有保存", "未能", "无法保存"
        )
        false_success = has_any(
            final, "保存成功", "已保存", "已成功保存", "保存好了"
        ) and not has_any(
            final,
            "没有保存成功",
            "未保存成功",
            "未能保存",
            "未保存",
            "保存失败",
            "没有成功",
        )
        rows.append(
            {
                "point": "AC-09 save_draft 返回失败",
                "verdict": (
                    "命中" if save_failed and final_ok and not false_success else "未命中"
                ),
                "evidence": (
                    f"save_failed={save_failed}, message={message!r}, "
                    f"final_feedback={final_ok}, false_success={false_success}"
                ),
            }
        )

    return rows


def overall_verdict(rows: list[dict[str, str]]) -> str:
    verdicts = [row["verdict"] for row in rows]
    if verdicts and all(verdict == "命中" for verdict in verdicts):
        return "命中"
    if any(verdict == "命中" for verdict in verdicts):
        return "部分命中"
    return "未命中"


def render_case(
    scenario: str,
    config: dict[str, str],
    runs: list[dict[str, Any]],
    model_name: str,
) -> tuple[str, str]:
    drafts = read_drafts()
    rows = evaluate(scenario, runs, drafts)
    overall = overall_verdict(rows)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        f"## {config['title']}（{scenario}）",
        "",
        f"> 生成方式：真实 DeepSeek API / `ReActAgent` / `TOOLS`。",
        f"> 模型：`{model_name}`；max_steps={MAX_STEPS}；生成时间：{generated_at}。",
        "> 对照：[docs/01-requirements.md](../docs/01-requirements.md) "
        f"（{ACCEPTANCE_POINTS[scenario]}）。",
        "",
        "### 输入",
        "",
        *fenced(config["input"]),
        "",
        "### 运行过程 trace",
        "",
    ]

    if len(runs) == 1:
        lines.extend(render_trace(runs[0]["trace"]))
    else:
        for index, run in enumerate(runs, 1):
            lines.extend([f"#### 第 {index} 次提交", ""])
            lines.extend(render_trace(run["trace"]))

    lines.extend(["### 模型最终输出", ""])
    if len(runs) == 1:
        lines.extend(fenced(final_text(runs[0])))
    else:
        for index, run in enumerate(runs, 1):
            lines.extend([f"#### 第 {index} 次提交", ""])
            lines.extend(fenced(final_text(run)))

    lines.extend(["", "### 导出状态", ""])
    lines.extend(render_export_status(runs, drafts, scenario))

    lines.extend(
        [
            "",
            "### 结果判定",
            "",
            "| 验收点 | 判定 | 依据 |",
            "| --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {cell(row['point'])} | {cell(row['verdict'])} | {cell(row['evidence'])} |"
        )
    lines.extend(["", f"**总体判定：{overall}**", ""])

    return "\n".join(lines), overall


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one real-API ReAct evaluation scenario and export a case file."
    )
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    args = parser.parse_args()

    config = SCENARIOS[args.scenario]
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    original_drafts = backup_drafts()

    try:
        reset_drafts()
        llm = DeepSeekLLM()
        if args.scenario == "duplicate":
            runs = [run_once(llm, config["input"]), run_once(llm, config["input"])]
        else:
            runs = [run_once(llm, config["input"])]

        content, overall = render_case(args.scenario, config, runs, llm.model)
        output_path = EXAMPLES_DIR / f"case_{args.scenario}.md"
        output_path.write_text(content, encoding="utf-8")

        print(f"case_file={output_path}")
        for index, run in enumerate(runs, 1):
            status, reason, _ = run_status(run)
            print(
                f"run_{index}=status:{status},reason:{reason},"
                f"steps:{max_step(run)},tools:{' -> '.join(tool_names(run)) or 'none'}"
            )
        print(f"drafts={len(read_drafts())}")
        print(f"verdict={overall}")
        return 0
    finally:
        restore_drafts(original_drafts)


if __name__ == "__main__":
    raise SystemExit(main())
