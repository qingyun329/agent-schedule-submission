"""Regression tests for the six ReAct scenarios in examples/.

These tests never call DeepSeek: a scripted MockLLM drives the existing
ReActAgent through deterministic tool sequences, while the real synthetic
tools supply the observations and draft persistence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from src.agent import ReActAgent
from src.llm import LLMResponse, MockLLM, ToolCall
from src.tools import TOOLS

ROOT = Path(__file__).resolve().parent.parent
DRAFTS_PATH = ROOT / "data" / "drafts.json"


@pytest.fixture(autouse=True)
def clean_drafts() -> None:
    """Every test starts and ends without runtime drafts."""

    DRAFTS_PATH.unlink(missing_ok=True)
    yield
    DRAFTS_PATH.unlink(missing_ok=True)


def read_drafts() -> list[dict[str, Any]]:
    if not DRAFTS_PATH.exists():
        return []
    payload = json.loads(DRAFTS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, list), f"drafts.json 根节点应为数组，实际：{payload!r}"
    return payload


def tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(call_id, name, arguments)])


def latest_result_in_messages(
    messages: list[dict[str, Any]], tool_name: str
) -> dict[str, Any]:
    """Find the latest parsed observation for a named tool."""

    names_by_call_id: dict[str, str] = {}
    latest: dict[str, Any] | None = None

    for message in messages:
        role = message.get("role")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                names_by_call_id[str(call.get("id", ""))] = str(
                    function.get("name", "")
                )
        elif role == "tool":
            name = names_by_call_id.get(str(message.get("tool_call_id", "")))
            if name != tool_name:
                continue
            try:
                candidate = json.loads(str(message.get("content", "")))
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                latest = candidate

    assert latest is not None, (
        f"没有找到工具 {tool_name!r} 的可解析 observation；"
        f"messages={messages!r}"
    )
    return latest


def all_results_in_messages(
    messages: list[dict[str, Any]], tool_name: str
) -> list[dict[str, Any]]:
    names_by_call_id: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                names_by_call_id[str(call.get("id", ""))] = str(
                    function.get("name", "")
                )
        elif role == "tool":
            name = names_by_call_id.get(str(message.get("tool_call_id", "")))
            if name != tool_name:
                continue
            try:
                payload = json.loads(str(message.get("content", "")))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                results.append(payload)

    return results


def latest_tool_result(agent: ReActAgent, tool_name: str) -> dict[str, Any]:
    return latest_result_in_messages(agent.messages, tool_name)


def tool_sequence(agent: ReActAgent) -> list[str]:
    return [
        str(entry["tool"])
        for entry in agent.trace
        if entry.get("tool")
    ]


def assert_finished(agent: ReActAgent, result: str | dict[str, str]) -> None:
    assert isinstance(result, str), (
        f"Agent 应返回最终回答，实际返回：{result!r}；trace={agent.trace!r}"
    )
    assert agent.trace, "Agent 没有产生 trace"
    assert agent.trace[-1].get("next_action") == "finish", (
        f"最后一步 next_action 应为 finish，实际：{agent.trace[-1]!r}"
    )
    assert all(entry.get("next_action") != "max_steps" for entry in agent.trace), (
        f"Agent 意外到达 max_steps：{agent.trace!r}"
    )


def run_script(
    script: list[LLMResponse | str | Callable[..., LLMResponse | str]],
    prompt: str,
) -> tuple[ReActAgent, str]:
    llm = MockLLM(script)
    agent = ReActAgent(llm=llm, tools=TOOLS, max_steps=8)
    result = agent.run(prompt)
    assert_finished(agent, result)
    return agent, result


def final_after_save(
    messages: list[dict[str, Any]], tools: dict[str, Any]
) -> str:
    payload = latest_result_in_messages(messages, "save_draft")
    data = payload.get("data") or {}
    return (
        f"草稿已保存，draft_id={data.get('draft_id')}，"
        "仅保存草稿，未真实发布。"
    )


def final_after_duplicate(
    messages: list[dict[str, Any]], tools: dict[str, Any]
) -> str:
    payload = latest_result_in_messages(messages, "save_draft")
    data = payload.get("data") or {}
    if data.get("duplicate"):
        return (
            f"相同草稿已存在，draft_id={data.get('draft_id')}，"
            "未重复创建。"
        )
    return f"草稿已保存，draft_id={data.get('draft_id')}。"


def final_after_conflict(
    messages: list[dict[str, Any]], tools: dict[str, Any]
) -> str:
    payload = latest_result_in_messages(messages, "query_slots")
    slots = (payload.get("data") or {}).get("available_slots") or []
    return (
        "18:00-18:30 已被占用；可用替代时段："
        + "、".join(str(slot) for slot in slots)
        + "。请确认是否改期，确认前不保存。"
    )


def final_after_missing(
    messages: list[dict[str, Any]], tools: dict[str, Any]
) -> str:
    payload = latest_result_in_messages(messages, "read_material")
    missing = (payload.get("data") or {}).get("missing_fields") or []
    return (
        "素材信息不完整，缺少 "
        + "、".join(str(field) for field in missing)
        + "，请补充后再排期；未保存草稿。"
    )


def final_after_rule(
    messages: list[dict[str, Any]], tools: dict[str, Any]
) -> str:
    payload = latest_result_in_messages(messages, "check_rules")
    data = payload.get("data") or {}
    reasons = "；".join(str(reason) for reason in data.get("risk_reasons") or [])
    return f"审核未通过（{data.get('risk_level')}）：{reasons}。未保存草稿。"


def final_after_save_failure(
    messages: list[dict[str, Any]], tools: dict[str, Any]
) -> str:
    payload = latest_result_in_messages(messages, "save_draft")
    return f"保存失败：{payload.get('message')}；草稿未保存。"


def test_normal_flow_saves_draft() -> None:
    agent, result = run_script(
        [
            tool_call("n1", "read_material", {"material_id": "M01"}),
            tool_call("n2", "check_rules", {"material_id": "M01"}),
            tool_call("n3", "query_slots", {"start_time": "19:00-19:30"}),
            tool_call(
                "n4",
                "save_draft",
                {
                    "material_id": "M01",
                    "slot": "19:00-19:30",
                    "notes": "用户已确认",
                },
            ),
            final_after_save,
        ],
        "素材 M01 就按 19:00-19:30 排，我已经确认，帮我保存草稿",
    )

    assert tool_sequence(agent) == [
        "read_material",
        "check_rules",
        "query_slots",
        "save_draft",
    ], f"正常路径工具顺序不正确：{tool_sequence(agent)!r}"

    check_data = latest_tool_result(agent, "check_rules").get("data") or {}
    assert check_data.get("passed") is True, (
        f"M01 应审核通过，实际：{check_data!r}"
    )

    query_data = latest_tool_result(agent, "query_slots").get("data") or {}
    assert "19:00-19:30" in (query_data.get("available_slots") or []), (
        f"19:00-19:30 应为空闲时段，实际：{query_data!r}"
    )

    save_payload = latest_tool_result(agent, "save_draft")
    save_data = save_payload.get("data") or {}
    assert save_payload.get("success") is True, (
        f"草稿保存应成功，实际：{save_payload!r}"
    )
    assert save_data.get("duplicate") is False, (
        f"首次保存不应标记 duplicate，实际：{save_data!r}"
    )

    draft_id = save_data.get("draft_id")
    assert draft_id, f"保存结果缺少 draft_id：{save_data!r}"
    assert draft_id in result, (
        f"最终回答应包含 draft_id={draft_id}，实际回答：{result!r}"
    )

    drafts = read_drafts()
    assert len(drafts) == 1, f"期望草稿 1 条，实际 {len(drafts)} 条：{drafts!r}"
    assert drafts[0].get("material_id") == "M01", (
        f"草稿素材应为 M01，实际：{drafts!r}"
    )
    assert drafts[0].get("slot") == "19:00-19:30", (
        f"草稿时段应为 19:00-19:30，实际：{drafts!r}"
    )
    assert drafts[0].get("draft_id") == draft_id, (
        f"草稿文件中的 draft_id 应与保存结果一致：{drafts!r}"
    )


def test_conflict_requires_confirmation() -> None:
    agent, result = run_script(
        [
            tool_call("c1", "read_material", {"material_id": "M01"}),
            tool_call("c2", "check_rules", {"material_id": "M01"}),
            tool_call("c3", "query_slots", {"start_time": "18:00-19:00"}),
            final_after_conflict,
        ],
        "素材 M01 需要排 18:00 发布，帮我处理一下",
    )

    assert tool_sequence(agent) == [
        "read_material",
        "check_rules",
        "query_slots",
    ], f"冲突路径工具顺序不正确：{tool_sequence(agent)!r}"

    query_data = latest_tool_result(agent, "query_slots").get("data") or {}
    slots = query_data.get("available_slots") or []
    assert "18:30-19:00" in slots, (
        f"应返回 18:30-19:00 替代时段，实际：{query_data!r}"
    )
    assert "18:30-19:00" in result, (
        f"最终回答应包含替代时段 18:30-19:00，实际：{result!r}"
    )
    assert "确认" in result, f"最终回答应要求确认，实际：{result!r}"

    drafts = read_drafts()
    assert drafts == [], (
        f"冲突场景在用户确认前不应产生草稿，实际 {len(drafts)} 条：{drafts!r}"
    )
    assert not any(draft.get("slot") == "18:00-18:30" for draft in drafts), (
        f"不应擅自保存 18:00-18:30，实际草稿：{drafts!r}"
    )


def test_duplicate_submission_is_idempotent() -> None:
    first_agent, first_result = run_script(
        [
            tool_call(
                "d1",
                "save_draft",
                {"material_id": "M01", "slot": "19:00-19:30"},
            ),
            final_after_duplicate,
        ],
        "素材 M01 按 19:00-19:30 保存草稿",
    )
    first_payload = latest_tool_result(first_agent, "save_draft")
    first_data = first_payload.get("data") or {}
    first_draft_id = first_data.get("draft_id")

    second_agent, second_result = run_script(
        [
            tool_call(
                "d2",
                "save_draft",
                {"material_id": "M01", "slot": "19:00-19:30"},
            ),
            final_after_duplicate,
        ],
        "素材 M01 按 19:00-19:30 保存草稿",
    )
    second_payload = latest_tool_result(second_agent, "save_draft")
    second_data = second_payload.get("data") or {}

    assert first_payload.get("success") is True, (
        f"第一次保存应成功，实际：{first_payload!r}"
    )
    assert first_data.get("duplicate") is False, (
        f"第一次保存不应是 duplicate，实际：{first_data!r}"
    )
    assert second_payload.get("success") is True, (
        f"第二次保存应成功返回已有草稿，实际：{second_payload!r}"
    )
    assert second_data.get("duplicate") is True, (
        f"第二次保存应标记 duplicate=true，实际：{second_data!r}"
    )
    assert second_data.get("draft_id") == first_draft_id, (
        "重复保存应沿用首次 draft_id，"
        f"实际：first={first_draft_id!r}, second={second_data.get('draft_id')!r}"
    )
    assert first_draft_id in first_result and first_draft_id in second_result, (
        f"两次最终回答都应包含同一 draft_id={first_draft_id}，"
        f"实际：first={first_result!r}, second={second_result!r}"
    )

    drafts = read_drafts()
    assert len(drafts) == 1, f"期望草稿 1 条，实际 {len(drafts)} 条：{drafts!r}"
    assert drafts[0].get("draft_id") == first_draft_id, (
        f"草稿文件应保留首次 draft_id，实际：{drafts!r}"
    )


def test_missing_fields_blocks_scheduling() -> None:
    agent, result = run_script(
        [
            tool_call("m1", "read_material", {"material_id": "M02"}),
            tool_call("m2", "check_rules", {"material_id": "M02"}),
            final_after_missing,
        ],
        "素材 M02 需要排期，帮我看看",
    )

    assert tool_sequence(agent) == ["read_material", "check_rules"], (
        f"缺字段路径工具顺序不正确：{tool_sequence(agent)!r}"
    )

    read_payload = latest_tool_result(agent, "read_material")
    read_data = read_payload.get("data") or {}
    assert read_data.get("has_all_required_fields") is False, (
        f"M02 应标记字段不完整，实际：{read_data!r}"
    )
    assert set(read_data.get("missing_fields") or []) == {"owner", "category"}, (
        f"M02 应缺少 owner、category，实际：{read_data!r}"
    )

    check_data = latest_tool_result(agent, "check_rules").get("data") or {}
    assert check_data.get("risk_level") == "confirm", (
        f"信息不足应返回 confirm 风险，实际：{check_data!r}"
    )

    assert "owner" in result and "category" in result, (
        f"最终回答应提示 owner 和 category 缺失，实际：{result!r}"
    )
    assert "补充" in result or "缺少" in result, (
        f"最终回答应要求补充信息，实际：{result!r}"
    )

    drafts = read_drafts()
    assert drafts == [], (
        f"信息不足不应产生草稿，实际 {len(drafts)} 条：{drafts!r}"
    )


def test_rule_risk_blocks_scheduling() -> None:
    agent, result = run_script(
        [
            tool_call("r1", "read_material", {"material_id": "M03"}),
            tool_call("r2", "check_rules", {"material_id": "M03"}),
            final_after_rule,
        ],
        "素材 M03 需要排 18:00 发布",
    )

    assert tool_sequence(agent) == ["read_material", "check_rules"], (
        f"规则风险路径工具顺序不正确：{tool_sequence(agent)!r}"
    )

    check_payload = latest_tool_result(agent, "check_rules")
    check_data = check_payload.get("data") or {}
    assert check_data.get("risk_level") in {"block", "confirm"}, (
        f"M03 应命中 block/confirm 风险，实际：{check_data!r}"
    )
    reasons = check_data.get("risk_reasons") or []
    assert reasons, f"M03 的 risk_reasons 不应为空：{check_data!r}"
    assert any("100%" in str(reason) or "治愈" in str(reason) for reason in reasons), (
        f"风险原因应写明 100%/治愈，实际：{reasons!r}"
    )
    assert "未保存" in result, f"最终回答应说明未保存，实际：{result!r}"

    drafts = read_drafts()
    assert drafts == [], (
        f"规则风险不应产生草稿，实际 {len(drafts)} 条：{drafts!r}"
    )


def test_save_failure_reported() -> None:
    agent, result = run_script(
        [
            tool_call("f1", "read_material", {"material_id": "M04"}),
            tool_call(
                "f2",
                "save_draft",
                {"material_id": "M04", "slot": "19:00-19:30"},
            ),
            final_after_save_failure,
        ],
        "素材 M04 排 19:00，帮我保存",
    )

    assert tool_sequence(agent) == ["read_material", "save_draft"], (
        f"保存失败路径工具顺序不正确：{tool_sequence(agent)!r}"
    )

    save_results = all_results_in_messages(agent.messages, "save_draft")
    assert save_results, "没有找到 save_draft 的结果"
    assert all(payload.get("success") is False for payload in save_results), (
        f"save_draft 不应出现 success=true，实际：{save_results!r}"
    )

    save_payload = save_results[-1]
    assert save_payload.get("success") is False, (
        f"save_draft 应失败，实际：{save_payload!r}"
    )
    assert "暂不可用" in str(save_payload.get("message", "")), (
        f"失败信息应包含“暂不可用”，实际：{save_payload!r}"
    )
    assert "未保存" in result or "失败" in result, (
        f"最终回答应明确未保存/失败，实际：{result!r}"
    )

    drafts = read_drafts()
    assert drafts == [], (
        f"保存失败不应产生草稿，实际 {len(drafts)} 条：{drafts!r}"
    )
