"""LLM adapters for the minimal ReAct agent skeleton."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ToolCall:
    """A normalized tool call returned by an LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    argument_error: str | None = None


@dataclass
class LLMResponse:
    """The small response shape the agent loop depends on."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    """Interface implemented by DeepSeekLLM and MockLLM."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: dict[str, dict[str, Any]],
    ) -> LLMResponse:
        ...


def to_openai_tools(tools: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert the local tool registry into OpenAI-compatible tool schemas."""

    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec.get("description", ""),
                "parameters": spec.get("parameters")
                or {"type": "object", "properties": {}},
            },
        }
        for name, spec in tools.items()
    ]


class DeepSeekLLM:
    """DeepSeek chat model through its OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.api_key = (api_key or os.getenv("DEEPSEEK_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY is not configured; use MockLLM for offline runs."
            )

        self.base_url = (
            base_url
            or os.getenv("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com"
        ).strip()
        self.model = model or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"
        self.temperature = temperature

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on local install
            raise RuntimeError(
                "The 'openai' package is required for DeepSeekLLM. "
                "Run: pip install -r requirements.txt"
            ) from exc

        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: dict[str, dict[str, Any]],
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        completion = self._client.chat.completions.create(**kwargs)
        message = completion.choices[0].message

        tool_calls: list[ToolCall] = []
        for index, raw_call in enumerate(message.tool_calls or []):
            raw_arguments = raw_call.function.arguments or "{}"
            argument_error: str | None = None
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                arguments = {}
                argument_error = f"{type(exc).__name__}: {exc}"

            tool_calls.append(
                ToolCall(
                    id=raw_call.id or f"call_{index + 1}",
                    name=raw_call.function.name,
                    arguments=arguments,
                    argument_error=argument_error,
                )
            )

        return LLMResponse(content=message.content or "", tool_calls=tool_calls)


class MockLLM:
    """Scriptable offline model used to verify the ReAct loop.

    Pass a list of LLMResponse objects (or strings/callables) to play back a
    deterministic conversation. When the script is exhausted, it returns a
    harmless echo answer so the CLI can run without any credentials.
    """

    def __init__(
        self,
        responses: list[LLMResponse | str | Callable[..., LLMResponse | str]]
        | None = None,
        default_answer: str | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self.default_answer = default_answer
        self.calls: list[list[dict[str, Any]]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: dict[str, dict[str, Any]],
    ) -> LLMResponse:
        self.calls.append(copy.deepcopy(messages))

        if self._responses:
            item = self._responses.pop(0)
            if callable(item):
                item = item(messages, tools)
            if isinstance(item, str):
                return LLMResponse(content=item)
            if isinstance(item, LLMResponse):
                return item
            raise TypeError(
                "MockLLM script items must be LLMResponse, str, or a callable "
                "returning one of those."
            )

        if self.default_answer is not None:
            return LLMResponse(content=self.default_answer)

        last_user = next(
            (
                str(message.get("content", ""))
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        return LLMResponse(
            content=f"[MockLLM] 已收到：{last_user}。离线模式未调用真实模型。"
        )
