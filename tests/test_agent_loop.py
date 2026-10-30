"""Acceptance-style tests for the minimal ReAct loop.

The "add" tool is intentionally temporary: it exists only to prove that the
loop executes multiple tool calls and feeds observations back to the model.
"""

from __future__ import annotations

import json
from typing import Any

from src.agent import ReActAgent
from src.llm import LLMResponse, MockLLM, ToolCall


def add(a: int, b: int) -> int:
    return a + b


DEMO_TOOLS: dict[str, dict[str, Any]] = {
    "add": {
        "func": add,
        "description": "把两个整数相加并返回和。",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    }
}


def test_three_step_react_loop() -> None:
    llm = MockLLM(
        [
            LLMResponse(
                tool_calls=[ToolCall("call-1", "add", {"a": 2, "b": 3})]
            ),
            LLMResponse(
                tool_calls=[ToolCall("call-2", "add", {"a": 5, "b": 4})]
            ),
            LLMResponse(
                tool_calls=[ToolCall("call-3", "add", {"a": 9, "b": 1})]
            ),
            LLMResponse(content="三步累加完成，最终结果是 10。"),
        ]
    )
    agent = ReActAgent(llm=llm, tools=DEMO_TOOLS, max_steps=6)
    result = agent.run("请连续调用 add 三次，逐步累加，最后告诉我结果。")

    assert result == "三步累加完成，最终结果是 10。"
    assert len(llm.calls) == 4
    assert [entry["step"] for entry in agent.trace] == [1, 2, 3, 4]
    assert [entry["next_action"] for entry in agent.trace] == [
        "continue",
        "continue",
        "continue",
        "finish",
    ]

    tool_steps = [entry for entry in agent.trace if entry["tool"] == "add"]
    assert len(tool_steps) == 3
    assert [entry["result_summary"] for entry in tool_steps] == ["5", "9", "10"]

    # The last LLM call must see all three tool observations.
    last_call_messages = llm.calls[-1]
    observations = [
        message["content"]
        for message in last_call_messages
        if message.get("role") == "tool"
    ]
    assert observations == ["5", "9", "10"]

    print("\n=== ReAct three-step run ===")
    print(f"final_answer: {result}")
    print(f"tool_steps: {len(tool_steps)}")
    print("=== trace ===")
    print(json.dumps(agent.trace, ensure_ascii=False, indent=2))


def test_tool_exception_becomes_observation() -> None:
    def explode() -> None:
        raise RuntimeError("boom")

    tools = {
        "explode": {
            "func": explode,
            "description": "A deliberately failing tool.",
            "parameters": {"type": "object", "properties": {}},
        }
    }
    llm = MockLLM(
        [
            LLMResponse(tool_calls=[ToolCall("call-err", "explode", {})]),
            LLMResponse(content="工具执行失败，已停止。"),
        ]
    )
    agent = ReActAgent(llm=llm, tools=tools, max_steps=3)
    result = agent.run("调用会失败的工具")

    assert result == "工具执行失败，已停止。"
    assert agent.trace[0]["result_summary"].startswith("ERROR:")
    observations = [
        message["content"]
        for message in llm.calls[-1]
        if message.get("role") == "tool"
    ]
    assert observations == ["ERROR: tool 'explode' raised RuntimeError: boom"]


def test_max_steps_returns_unfinished() -> None:
    llm = MockLLM(
        [
            LLMResponse(tool_calls=[ToolCall(f"call-{i}", "add", {"a": 1, "b": 1})])
            for i in range(10)
        ]
    )
    agent = ReActAgent(llm=llm, tools=DEMO_TOOLS, max_steps=2)
    result = agent.run("一直调用工具")

    assert result == {"status": "unfinished", "reason": "max_steps"}
    assert [entry["next_action"] for entry in agent.trace] == [
        "continue",
        "max_steps",
    ]
