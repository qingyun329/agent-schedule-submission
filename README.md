# 素材审核与发布排期 Agent

> 小影校招「AI Agent 开发岗位」考核项目第 1 题  
> 基于 DeepSeek ReAct 模式，让运营人员用自然语言完成视频素材的规则审核、排期冲突检查和草稿保存。

## 项目简介

内容团队只需给出素材 ID 和发布时间要求，Agent 就会通过 ReAct 循环自主判断下一步该做什么：读取素材、执行审核规则、查询可用时段、在确认后保存草稿。模型负责决策，工具负责返回事实。

项目坚持两条业务边界：

- **只保存排期草稿，不真实发布内容。**
- **未经用户明确确认，不擅自修改硬性发布时间要求，也不自动改期保存。**

## 快速开始

### 1. 环境要求

- Python **3.10+**（当前已在 3.12.7 上验证）
- 可访问 DeepSeek API 的网络环境
- DeepSeek API Key（仅真实模型模式需要）

安装完整依赖：

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` 包含 `openai`、`python-dotenv`、`pytest` 和 `pydantic`。其中 `python-dotenv` 是自动加载 `.env` 所需的唯一新增依赖；完整运行仍然需要 `openai`，测试需要 `pytest`。如果只想补齐 `.env` 加载能力，也可以单独执行：

```bash
pip install python-dotenv
```

### 2. 配置环境变量

复制模板：

```bash
copy .env.example .env    # Windows
cp .env.example .env      # macOS / Linux
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`。`DEEPSEEK_BASE_URL` 为可选项，不填时使用 DeepSeek 官方地址。

`.env` 只保存在本地，`.gitignore` 已忽略该文件，请勿提交任何真实密钥。

### 3. 没有 Key 也能启动

未配置 Key 时，命令行入口会自动回退到 `MockLLM`：

```bash
python -m src.cli "排期 M01 19:00"
```

此时可以验证 CLI、Agent 循环和工具注册链路是否正常，但 `MockLLM` 只是离线回显，**不能证明真实模型的决策质量**。真实模型效果请以 `examples/` 下的运行记录为准。

## 核心能力与验收对照表

验收点编号严格对应 [docs/01-requirements.md](docs/01-requirements.md) 中的 AC-01 至 AC-12。

| 能力 | 验收点 |
| --- | --- |
| 正常排期：读取素材 → 规则审核 → 查询时段 → 保存草稿 | AC-01 正常素材 + 空闲时段 |
| 素材读取与完整性校验，检测 `missing fields` | AC-02 缺少审核所需字段 |
| 规则风险识别：绝对化用语、医疗健康类内容 | AC-03 规则风险拦截；AC-04 需人工确认 |
| 时段冲突检测与替代方案 | AC-05 目标时段冲突（拒绝/确认分支见 AC-06、AC-07） |
| 用户确认前不擅自保存、不擅自改期 | AC-05、AC-11、AC-12 |
| 重复提交幂等：相同素材 + 相同最终时段只产生一份草稿 | AC-08 重复提交 |
| 存储服务失败如实上报，不虚报成功 | AC-09 `save_draft` 失败 |
| 只保存草稿，不触发真实发布 | AC-10 全流程检查 |

## 运行命令（评审可复现）

### 1. ReAct 对话演示

```bash
python -m src.cli "排期 M01 19:00"
```

- 配置真实 Key 时：调用 DeepSeek，模型自行选择工具并完成 ReAct 决策。
- 未配置 Key 时：自动回退 `MockLLM`，输出离线回显。
- 需要查看每一步 trace，可追加 `--trace`；需要限制循环上限，可传 `--max-steps N`。

无 Key 时的典型输出：

```text
[llm] 未配置 DEEPSEEK_API_KEY，使用 MockLLM（离线）。
[MockLLM] 已收到：排期 M01 19:00。离线模式未调用真实模型。
```

### 2. 纯业务工具演示

```bash
python -m src.demo_tools
```

直接通过 `TOOLS` 注册表调用四个业务工具，不经过模型，用来验证工具层行为：

- `read_material` 的字段完整性检查；
- `check_rules` 的 `ok / confirm / block` 风险结果；
- `query_slots` 的 30 分钟粒度空闲时段；
- `save_draft` 的首次保存、重复保存和 M04 保存失败。

该命令会实际写入 `data/drafts.json`。重复运行同一素材和时段时，第二次会显示 `duplicate=true`，这是幂等行为。

### 3. 完整测试

```bash
python -m pytest tests/ -v
```

预期结果：**9 passed**。

- `tests/test_agent_loop.py`：3 条 ReAct 骨架测试；
- `tests/test_scenarios.py`：6 条场景回归测试，对应六条评估路径。

回归测试全部使用 `MockLLM`，不会调用真实 API，也不会实例化 `DeepSeekLLM` 或使用 Key；测试 fixture 会在每条用例前后清理 `data/drafts.json`。

## 评估证据

`examples/` 下的 6 个 case 文件均由**真实 DeepSeek API 运行**生成，不是 MockLLM 回放，也不是手编 trace。每个文件包含用户输入、逐步工具 trace、模型最终输出、导出状态和验收判定。

| Case | 结论 |
| --- | --- |
| [case_normal.md](examples/case_normal.md) | 完整四步链，草稿保存成功 |
| [case_conflict.md](examples/case_conflict.md) | 发现 18:00 冲突后给出 18:30-19:00 替代时段并请求确认，未擅自保存 |
| [case_duplicate.md](examples/case_duplicate.md) | 重复提交返回 `duplicate=true`，两次 `draft_id` 一致，草稿只有 1 条 |
| [case_missing.md](examples/case_missing.md) | 返回缺失字段 `owner`、`category` 并要求补充，暂停排期 |
| [case_rule.md](examples/case_rule.md) | 命中绝对化用语和医疗健康规则，拦截排期并给出原因 |
| [case_save_fail.md](examples/case_save_fail.md) | 两次保存均失败，如实上报“草稿存储服务暂不可用”，未产生草稿 |

几点补充说明：

- `case_normal` 的输入明确确认了 `19:00-19:30`。如果用户只说“排到 19:00”，模型可能先请求确认，这是预期的确认机制，不应被理解为自动保存。
- `case_save_fail` 的首次自动判定曾把“没有保存成功”误识别为成功声明。这是评估器的关键词判定缺陷，不是模型或工具行为；修正判定逻辑后重新运行，最终记录的是真实的两轮保存失败链路。
- 六个 case 均保留了原始工具调用和 observation 摘要，没有为了“看起来正确”而修改 `agent.py`、`tools.py` 或生成文件中的决策过程。

## 项目结构

```text
agent-schedule-submission/
├── data/                         # 合成数据 + 运行时草稿
│   ├── materials.json            # M01-M04 素材
│   ├── rules.json                # rule_001 / rule_002
│   ├── schedule.json             # 已有排期，18:00-18:30 被占用
│   └── drafts.json               # 运行时生成，测试/评估会清理
├── docs/                         # 需求与过程文档
│   ├── 01-requirements.md
│   ├── 02-solution.md
│   ├── 03-evaluation.md
│   ├── 04-ai-usage.md
│   └── 05-retrospective.md
├── examples/                     # 真实 API 评估 trace
│   ├── case_normal.md
│   ├── case_conflict.md
│   ├── case_duplicate.md
│   ├── case_missing.md
│   ├── case_rule.md
│   └── case_save_fail.md
├── src/
│   ├── agent.py                  # ReAct 循环
│   ├── llm.py                    # DeepSeekLLM / MockLLM
│   ├── tools.py                  # 四个业务工具 + TOOLS 注册表
│   ├── cli.py                    # 命令行入口
│   ├── demo_tools.py             # 工具层演示
│   ├── run_eval.py               # 真实 API 评估脚本
│   └── __init__.py
├── tests/
│   ├── test_agent_loop.py        # ReAct 骨架测试
│   └── test_scenarios.py         # 六条场景回归测试
├── .env.example
├── requirements.txt
└── README.md
```

## 已知限制与说明

- **规则目前是简化版**：只覆盖关键词绝对化用语和医疗健康分类，真实生产需要更多规则维度、严重级别、权重和规则版本管理。
- **时段粒度为 30 分钟**：当前按固定 30 分钟切片处理，未支持跨天、周期性排期、不同渠道的独立日历等复杂场景。
- **草稿存储是本地 JSON**：`data/drafts.json` 仅用于演示，不是真实发布系统，也没有并发写入锁和多用户隔离。
- **MockLLM 只能演示流程**：它不评估真实语义，也不能证明模型决策效果；真实效果以 `examples/` 中的 DeepSeek 运行记录为准。
- **真实模型调用默认 `max_steps=8`**：足够覆盖当前六条路径，更长的工具链或多轮确认场景可能需要调高上限，并结合超时与重试策略。
