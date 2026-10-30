"""Minimal ReAct loop: LLM -> tool call -> observation -> LLM."""

from __future__ import annotations

import json
from typing import Any

from .llm import ChatModel, LLMResponse, ToolCall

ToolRegistry = dict[str, dict[str, Any]]
Message = dict[str, Any]

MAX_SUMMARY_CHARS = 300

DEFAULT_SYSTEM_PROMPT = """你是一个 ReAct Agent，通过“推理 -> 调用工具 -> 观察结果”循环完成任务。
规则：
1. 需要外部信息或执行动作时，调用已注册的工具。
2. 认真阅读工具返回的 observation；如果返回 ERROR，说明失败原因或调整方案。
3. 信息足够时直接给出最终回答，不要编造工具结果。
4. 一次只推进一个明确目标，不要重复执行已经成功的同一次操作。"""


class ReActAgent:
    """A small, dependency-free ReAct loop over a dict-based tool registry."""

    def __init__(
        self,
        llm: ChatModel,
        tools: ToolRegistry,
        max_steps: int = 8,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")

        self.llm = llm
        self.tools = dict(tools)
        self.max_steps = max_steps
        self.system_prompt = system_prompt

        self.messages: list[Message] = []
        self.trace: list[dict[str, Any]] = []

    def run(self, user_input: str) -> str | dict[str, str]:
        """Run the loop and return either the final answer or an unfinished status."""

        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]
        self.trace = []

        for step in range(1, self.max_steps + 1):
            response = self.llm.chat(self.messages, self.tools)

            if not response.tool_calls:
                answer = response.content or ""
                self.trace.append(
                    {
                        "step": step,
                        "tool": None,
                        "arguments": {},
                        "result_summary": _summarize(answer),
                        "next_action": "finish",
                    }
                )
                return answer

            self._append_assistant_message(response)

            for index, call in enumerate(response.tool_calls):
                observation = self._execute_tool(call)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": observation,
                    }
                )

                is_last_call = index == len(response.tool_calls) - 1
                next_action = (
                    "max_steps"
                    if is_last_call and step >= self.max_steps
                    else "continue"
                )
                self.trace.append(
                    {
                        "step": step,
                        "tool": call.name,
                        "arguments": dict(call.arguments),
                        "result_summary": _summarize(observation),
                        "next_action": next_action,
                    }
                )

        return {"status": "unfinished", "reason": "max_steps"}

    def _append_assistant_message(self, response: LLMResponse) -> None:
        """Preserve the assistant's tool calls before adding tool observations."""

        tool_calls = []
        for call in response.tool_calls:
            arguments = {} if call.argument_error else call.arguments
            tool_calls.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            arguments, ensure_ascii=False, default=str
                        ),
                    },
                }
            )

        self.messages.append(
            {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": tool_calls,
            }
        )

    def _execute_tool(self, call: ToolCall) -> str:
        """Execute one tool. Every failure becomes an observation, never an exception."""

        spec = self.tools.get(call.name)
        if spec is None:
            return (
                f"ERROR: unknown tool '{call.name}'. "
                f"Available tools: {sorted(self.tools)}"
            )
        if not isinstance(spec, dict):
            return f"ERROR: tool '{call.name}' has an invalid registry entry"

        if call.argument_error:
            return (
                f"ERROR: invalid arguments for tool '{call.name}': "
                f"{call.argument_error}"
            )

        if not isinstance(call.arguments, dict):
            return f"ERROR: arguments for tool '{call.name}' must be an object"

        func = spec.get("func")
        if not callable(func):
            return f"ERROR: tool '{call.name}' has no callable 'func'"

        try:
            result = func(**call.arguments)
        except Exception as exc:  # tool failures must not break the loop
            return f"ERROR: tool '{call.name}' raised {type(exc).__name__}: {exc}"

        return _stringify(result)


def _stringify(value: Any) -> str:
    """Render a tool result as the text observation expected by the LLM."""

    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return f"<unserializable result: {type(value).__name__}>"


def _summarize(value: str) -> str:
    """Keep trace entries readable even when a tool returns a large payload."""

    text = " ".join(value.split())
    if len(text) <= MAX_SUMMARY_CHARS:
        return text
    return text[: MAX_SUMMARY_CHARS - 3] + "..."
