"""Business tools for material review and draft scheduling.

The tools only return facts. They do not decide whether a material should be
scheduled; that decision belongs to the ReAct agent and the user.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

DATA_DIR = Path(
    os.environ.get(
        "SCHEDULE_AGENT_DATA_DIR",
        Path(__file__).resolve().parent.parent / "data",
    )
).resolve()

REQUIRED_FIELDS = ("title", "owner", "category", "duration_minutes")
SLOT_MINUTES = 30

_TIME_RANGE_RE = re.compile(
    r"^(?P<start_h>[01]\d|2[0-3]):(?P<start_m>[0-5]\d)"
    r"-(?P<end_h>[01]\d|2[0-3]):(?P<end_m>[0-5]\d)$"
)
_RISK_ORDER = {"ok": 0, "confirm": 1, "block": 2}


def _result(
    success: bool,
    data: dict[str, Any] | None = None,
    message: str = "",
) -> dict[str, Any]:
    return {"success": success, "data": data, "message": message}


def _safe_tool(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Guarantee the uniform result shape even for unexpected failures."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            return _result(
                False,
                None,
                f"工具执行失败：{type(exc).__name__}: {exc}",
            )

    return wrapper


def _read_json_file(
    name: str,
    default: Any = None,
    required: bool = False,
) -> Any:
    path = DATA_DIR / name
    if not path.exists():
        if required:
            raise FileNotFoundError(f"{name} 不存在")
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_file(name: str, payload: Any) -> None:
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return not value
    return False


def _parse_time_range(value: str) -> tuple[int, int] | None:
    match = _TIME_RANGE_RE.fullmatch(value.strip())
    if match is None:
        return None

    start = int(match["start_h"]) * 60 + int(match["start_m"])
    end = int(match["end_h"]) * 60 + int(match["end_m"])
    if start >= end:
        return None
    if start % SLOT_MINUTES or end % SLOT_MINUTES:
        return None
    return start, end


def _format_minutes(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _higher_risk(current: str, candidate: str) -> str:
    if _RISK_ORDER.get(candidate, -1) > _RISK_ORDER.get(current, -1):
        return candidate
    return current


def _match_rule(rule: dict[str, Any], material: dict[str, Any]) -> str | None:
    rule_type = str(rule.get("type", "")).strip()

    if rule_type == "keyword_any":
        fields = rule.get("fields") or ["title"]
        if not isinstance(fields, list):
            return None

        text = "\n".join(
            str(material[field])
            for field in fields
            if field in material and material[field] is not None
        ).casefold()

        matched: list[str] = []
        keywords = rule.get("keywords") or []
        if not isinstance(keywords, list):
            return None
        for keyword in keywords:
            needle = str(keyword).strip()
            if needle and needle.casefold() in text and needle not in matched:
                matched.append(needle)

        if not matched:
            return None

        reason = str(rule.get("reason") or "命中规则 {rule_id}：{matched}")
        return reason.replace("{matched}", "、".join(matched)).replace(
            "{rule_id}", str(rule.get("rule_id", ""))
        )

    if rule_type == "field_equals":
        field = rule.get("field")
        expected = rule.get("value")
        if not field or expected is None:
            return None
        actual = material.get(str(field))
        if actual is None:
            return None
        if str(actual).strip().casefold() != str(expected).strip().casefold():
            return None
        return str(rule.get("reason") or f"{field} 匹配 {expected}")

    return None


def _occupied_ranges() -> list[tuple[int, int]]:
    schedule = _read_json_file("schedule.json", required=True)
    if isinstance(schedule, dict):
        entries = schedule.get("occupied", [])
    elif isinstance(schedule, list):
        entries = schedule
    else:
        raise ValueError("schedule.json 根节点应为对象或数组")

    if not isinstance(entries, list):
        raise ValueError("schedule.json 的 occupied 应为数组")

    ranges: list[tuple[int, int]] = []
    for entry in entries:
        slot: str | None = None
        if isinstance(entry, str):
            slot = entry
        elif isinstance(entry, dict):
            slot = entry.get("slot")
            if not slot and entry.get("start") and entry.get("end"):
                slot = f"{entry['start']}-{entry['end']}"
        if not slot:
            continue

        parsed = _parse_time_range(str(slot))
        if parsed is None:
            raise ValueError(f"排期中的时段格式错误：{slot}")
        ranges.append(parsed)

    return ranges


@_safe_tool
def read_material(material_id: str) -> dict[str, Any]:
    """Read a material and report which required fields are missing."""

    materials = _read_json_file("materials.json", required=True)
    if not isinstance(materials, list):
        return _result(False, None, "素材数据格式错误：根节点应为数组")

    target = str(material_id).strip()
    for item in materials:
        if not isinstance(item, dict) or str(item.get("material_id", "")).strip() != target:
            continue

        material = dict(item)
        missing_fields = [
            field for field in REQUIRED_FIELDS if _is_missing(material.get(field))
        ]
        material["required_fields"] = list(REQUIRED_FIELDS)
        material["has_all_required_fields"] = not missing_fields
        material["missing_fields"] = missing_fields
        return _result(True, material, "素材读取成功")

    return _result(False, None, "素材不存在")


@_safe_tool
def check_rules(material_id: str) -> dict[str, Any]:
    """Check one material against rules.json and return the aggregate risk."""

    material_result = read_material(material_id)
    if not material_result["success"]:
        return _result(False, None, material_result["message"])

    material = material_result["data"] or {}
    rules = _read_json_file("rules.json", required=True)
    if isinstance(rules, dict):
        rules = rules.get("rules", [])
    if not isinstance(rules, list):
        return _result(False, None, "审核规则格式错误：根节点应为数组")

    risk_level = "ok"
    risk_reasons: list[str] = []

    missing_fields = material.get("missing_fields") or []
    if missing_fields:
        risk_level = "confirm"
        risk_reasons.append(
            "素材信息不完整，缺少字段：" + "、".join(missing_fields)
        )

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        matched_reason = _match_rule(rule, material)
        if not matched_reason:
            continue

        rule_level = str(rule.get("risk_level", "confirm"))
        if rule_level not in _RISK_ORDER:
            continue
        risk_level = _higher_risk(risk_level, rule_level)
        if matched_reason not in risk_reasons:
            risk_reasons.append(matched_reason)

    passed = risk_level == "ok"
    return _result(
        True,
        {
            "passed": passed,
            "risk_level": risk_level,
            "risk_reasons": risk_reasons,
            "material_id": str(material_id).strip(),
        },
        "未命中风险规则" if passed else "命中风险规则，需处理",
    )


@_safe_tool
def query_slots(start_time: str, end_time: str | None = None) -> dict[str, Any]:
    """Return free 30-minute slots in a time range.

    ``start_time`` normally contains the whole range ("18:00-20:00"). For
    compatibility, separate ``start_time``/``end_time`` values are also
    accepted.
    """

    if end_time:
        range_text = f"{str(start_time).strip()}-{str(end_time).strip()}"
    else:
        range_text = str(start_time).strip()

    parsed = _parse_time_range(range_text)
    if parsed is None:
        return _result(
            False,
            None,
            "时间范围格式错误，应为 30 分钟对齐的 HH:MM-HH:MM，例如 18:00-20:00",
        )

    start, end = parsed
    occupied = _occupied_ranges()
    available: list[str] = []

    cursor = start
    while cursor + SLOT_MINUTES <= end:
        slot_start = cursor
        slot_end = cursor + SLOT_MINUTES
        overlaps = any(
            slot_start < busy_end and busy_start < slot_end
            for busy_start, busy_end in occupied
        )
        if not overlaps:
            available.append(
                f"{_format_minutes(slot_start)}-{_format_minutes(slot_end)}"
            )
        cursor += SLOT_MINUTES

    return _result(
        True,
        {
            "available_slots": available,
            "range": f"{_format_minutes(start)}-{_format_minutes(end)}",
            "slot_minutes": SLOT_MINUTES,
        },
        f"查询完成，可用时段 {len(available)} 个",
    )


@_safe_tool
def save_draft(
    material_id: str,
    slot: str,
    notes: str = "",
) -> dict[str, Any]:
    """Save a draft, idempotently, without publishing anything."""

    material_result = read_material(material_id)
    if not material_result["success"]:
        return _result(False, None, material_result["message"])

    material = material_result["data"] or {}
    if bool(material.get("_force_save_failure")):
        return _result(False, None, "草稿存储服务暂不可用")

    parsed = _parse_time_range(str(slot).strip())
    if parsed is None or parsed[1] - parsed[0] != SLOT_MINUTES:
        return _result(
            False,
            None,
            "时段格式错误，应为 HH:MM-HH:MM 的 30 分钟时段，例如 19:00-19:30",
        )

    normalized_material_id = str(material_id).strip()
    normalized_slot = f"{_format_minutes(parsed[0])}-{_format_minutes(parsed[1])}"

    try:
        drafts = _read_json_file("drafts.json", default=[], required=False)
    except (OSError, json.JSONDecodeError) as exc:
        return _result(False, None, f"草稿数据读取失败：{exc}")
    if drafts is None:
        drafts = []
    if not isinstance(drafts, list):
        return _result(False, None, "草稿数据格式错误：根节点应为数组")

    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        if (
            str(draft.get("material_id", "")).strip() == normalized_material_id
            and str(draft.get("slot", "")).strip() == normalized_slot
        ):
            return _result(
                True,
                {
                    "draft_id": str(draft.get("draft_id", "")),
                    "duplicate": True,
                    "material_id": normalized_material_id,
                    "slot": normalized_slot,
                },
                "相同素材和时段已存在草稿，未重复创建",
            )

    draft = {
        "draft_id": f"draft_{uuid.uuid4().hex[:12]}",
        "material_id": normalized_material_id,
        "slot": normalized_slot,
        "notes": str(notes or ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    drafts.append(draft)

    try:
        _write_json_file("drafts.json", drafts)
    except OSError as exc:
        return _result(False, None, f"草稿保存失败：{exc}")

    return _result(
        True,
        {
            "draft_id": draft["draft_id"],
            "duplicate": False,
            "material_id": normalized_material_id,
            "slot": normalized_slot,
        },
        "草稿保存成功",
    )


TOOLS: dict[str, dict] = {
    "read_material": {
        "func": read_material,
        "description": (
            "读取指定素材的元数据，并检查 title、owner、category、"
            "duration_minutes 是否完整。需要确认素材是否存在、缺少哪些字段时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "素材 ID，例如 M01。",
                }
            },
            "required": ["material_id"],
            "additionalProperties": False,
        },
    },
    "check_rules": {
        "func": check_rules,
        "description": (
            "对指定素材执行审核规则，返回是否通过、风险等级"
            "（ok/confirm/block）和风险原因。排期前应调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "需要审核的素材 ID，例如 M03。",
                }
            },
            "required": ["material_id"],
            "additionalProperties": False,
        },
    },
    "query_slots": {
        "func": query_slots,
        "description": (
            "查询给定时间范围内未被占用的 30 分钟发布时段，"
            "返回 available_slots 列表。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": (
                        "时间范围，格式 HH:MM-HH:MM，例如 18:00-20:00。"
                        "如果单独传入开始时间，可再提供 end_time。"
                    ),
                },
                "end_time": {
                    "type": "string",
                    "description": "可选的结束时间，格式 HH:MM，例如 20:00。",
                },
            },
            "required": ["start_time"],
            "additionalProperties": False,
        },
    },
    "save_draft": {
        "func": save_draft,
        "description": (
            "保存排期草稿，不会真实发布。仅应在素材通过审核、信息完整且"
            "用户确认最终时段后调用。相同素材和时段的重复调用会返回已有草稿。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "素材 ID，例如 M01。",
                },
                "slot": {
                    "type": "string",
                    "description": "30 分钟时段，格式 HH:MM-HH:MM，例如 19:00-19:30。",
                },
                "notes": {
                    "type": "string",
                    "description": "可选备注。",
                },
            },
            "required": ["material_id", "slot"],
            "additionalProperties": False,
        },
    },
}

__all__ = [
    "read_material",
    "check_rules",
    "query_slots",
    "save_draft",
    "TOOLS",
    "REQUIRED_FIELDS",
]
