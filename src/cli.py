"""Command-line entry point for the ReAct agent skeleton."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .agent import ReActAgent
from .llm import DeepSeekLLM, MockLLM
from .tools import TOOLS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Run the minimal ReAct agent with DeepSeek or the offline MockLLM.",
    )
    parser.add_argument("prompt", help='用户输入，例如："排期 M01 19:00"')
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="最大 ReAct 循环步数（默认：8）",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="在回答后打印完整 trace JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if api_key:
        try:
            llm = DeepSeekLLM()
        except Exception as exc:
            print(f"[llm] DeepSeekLLM 初始化失败：{exc}", file=sys.stderr)
            return 1
    else:
        print(
            "[llm] 未配置 DEEPSEEK_API_KEY，使用 MockLLM（离线）。",
            file=sys.stderr,
        )
        llm = MockLLM()

    agent = ReActAgent(llm=llm, tools=TOOLS, max_steps=args.max_steps)
    result = agent.run(args.prompt)

    if isinstance(result, dict):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        exit_code = 2
    else:
        print(result)
        exit_code = 0

    if args.trace:
        print("\n[trace]")
        print(json.dumps(agent.trace, ensure_ascii=False, indent=2))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
