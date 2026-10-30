"""Run the business tools through the same TOOLS registry used by the agent."""

from __future__ import annotations

import json
from typing import Any

from .tools import TOOLS


def run_tool(name: str, label: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    print(f"\n=== {label} ===")
    result = TOOLS[name]["func"](*args, **kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    print("素材审核与发布排期 Agent — 业务工具演示")
    print("已注册工具：" + ", ".join(TOOLS))

    run_tool("read_material", 'read_material("M01")', "M01")
    run_tool("read_material", 'read_material("M02")', "M02")

    run_tool("check_rules", 'check_rules("M01")', "M01")
    run_tool("check_rules", 'check_rules("M03")', "M03")

    run_tool("query_slots", 'query_slots("18:00-20:00")', "18:00-20:00")

    run_tool(
        "save_draft",
        'save_draft("M01", "19:00-19:30") — 第 1 次',
        "M01",
        "19:00-19:30",
    )
    run_tool(
        "save_draft",
        'save_draft("M01", "19:00-19:30") — 第 2 次',
        "M01",
        "19:00-19:30",
    )

    run_tool(
        "save_draft",
        'save_draft("M04", "19:00-19:30")',
        "M04",
        "19:00-19:30",
    )


if __name__ == "__main__":
    main()
