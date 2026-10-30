# 评估方案与证据

## 1. 评估目标

本评估要验证的不是“工具函数能否单独跑通”，而是：

> 模型能否通过真实的 ReAct 循环，自主读取 observation、选择下一步工具，并完成素材审核、冲突检查、确认约束和草稿保存。

因此评估使用真实 DeepSeek API，而不是 MockLLM。MockLLM 只能证明循环和工具注册可运行，不能证明模型会做业务判断。

重点观察四类行为：

1. 是否先获取事实，再决定是否保存；
2. 是否在信息不足、规则风险或时段冲突时停止，而不是强行排期；
3. 是否遵守“用户确认前不擅自保存/改期”的边界；
4. 保存失败时是否如实上报，而不是虚报成功。

## 2. 评估设置

| 项目 | 设置 |
| --- | --- |
| 模型 | DeepSeek `deepseek-chat`，通过 `DeepSeekLLM` 的 OpenAI 兼容接口调用 |
| Agent | `ReActAgent`，未修改循环机制 |
| 工具 | `TOOLS` 中的 `read_material`、`check_rules`、`query_slots`、`save_draft` |
| 循环上限 | `max_steps=8` |
| 场景 | `normal`、`conflict`、`duplicate`、`missing`、`rule`、`save_fail` |
| 运行脚本 | `src/run_eval.py`，每个场景独立运行，输出 `examples/case_<scenario>.md` |
| 草稿隔离 | 每个场景运行前清理并隔离 `data/drafts.json`，运行结束后恢复运行前的草稿状态 |

### 2.1 输入设计

每个场景只给自然语言业务请求，不告诉模型工具调用顺序，也不在工具里写死素材编号分支。输入示例：

- normal：`素材 M01 就按 19:00-19:30 排，我已经确认这个时段，帮我保存草稿`
- conflict：`素材 M01 需要排 18:00 发布，帮我处理一下`
- duplicate：与 normal 相同，连续执行两次 `agent.run()`
- missing：`素材 M02 需要排期，帮我看看`
- rule：`素材 M03 需要排 18:00 发布`
- save_fail：`素材 M04 排 19:00，帮我保存`

### 2.2 记录内容

每个 case 文件包含：

- 用户输入；
- 逐步 trace：step、tool、arguments、result_summary、next_action；
- 模型最终输出；
- 导出状态：运行状态、结束原因、工具顺序、草稿数量；
- 结果判定：对照 `docs/01-requirements.md` 的验收点。

trace 直接来自 `agent.trace`，最终输出直接来自 DeepSeek 返回的 assistant content；没有把固定脚本写成“模型输出”。

## 3. 六个场景的判定标准与结果

| 场景 | 预期决策 | 实际工具序列 | 最终结果 |
| --- | --- | --- | --- |
| normal | 审核通过后查询空闲时段，确认后保存草稿 | `read_material → check_rules → query_slots → save_draft` | 命中：草稿保存成功，返回 `draft_id` |
| conflict | 发现 18:00 被占用，给出替代时段并请求确认，不擅自保存 | `read_material → check_rules → query_slots` | 命中：返回 18:30-19:00，要求确认，草稿 0 条 |
| duplicate | 相同素材 + 时段重复保存只产生一份草稿 | 第一次 `read → check → query → save`；第二次 `read → check → save` | 命中：第二次 `duplicate=true`，沿用同一 `draft_id`，草稿 1 条 |
| missing | 返回缺失字段，暂停排期 | `read_material → check_rules` | 命中：提示缺 `owner`、`category`，草稿 0 条 |
| rule | 命中规则风险后拦截，不保存 | `read_material → check_rules → query_slots` | 命中：`risk_level=block`，说明 100%/治愈及医疗健康风险，草稿 0 条 |
| save_fail | 保存失败时如实上报，不虚构成功 | `read_material → check_rules → query_slots → save_draft → save_draft` | 命中：两次均返回“草稿存储服务暂不可用”，草稿 0 条 |

### 3.1 normal：完整四步链

`case_normal.md` 中，模型先读取 M01 并确认四个必填字段完整，再调用 `check_rules` 得到 `risk_level=ok`，随后查询 `19:00-19:30` 得到该时段空闲，最后调用 `save_draft`。保存结果包含 `draft_id`，模型在最终回答中明确说明“仅保存草稿，未真实发布”。

### 3.2 conflict：不越权

`case_conflict.md` 中，模型查询 `18:00-19:00`，观察到唯一可用时段是 `18:30-19:00`，于是向用户说明 18:00-18:30 已被占用，并列出“改排 18:30-19:00”或“换时间范围”两个选项。模型没有调用 `save_draft`，因此没有在用户确认前擅自改期。

### 3.3 duplicate：幂等

`case_duplicate.md` 连续执行两次完整提交：

- 第一次：`save_draft` 返回 `duplicate=false` 和新 `draft_id`；
- 第二次：`duplicate=true`，返回同一个 `draft_id`；
- 两次运行后 `data/drafts.json` 仍只有 1 条该素材 + 时段的草稿。

### 3.4 missing：信息不足暂停

`case_missing.md` 中，`read_material("M02")` 返回 `has_all_required_fields=false`、`missing_fields=["owner","category"]`，`check_rules` 以 `confirm` 返回同一缺失信息。模型没有查询时段，也没有保存，而是要求用户补齐字段。

### 3.5 rule：规则风险拦截

`case_rule.md` 中，`check_rules("M03")` 返回：

- `risk_level=block`；
- 绝对化用语命中 `100%`、`治愈`；
- 医疗健康类需要人工确认。

模型在最终回答中明确说“不能排期”，并解释修改标题、人工复审等后续动作。虽然它额外查询了时段作为参考，但没有调用 `save_draft`。

### 3.6 save_fail：失败如实上报

`case_save_fail.md` 中，M04 带有 `_force_save_failure=true`，`save_draft` 两次都返回：

```text
{"success": false, "data": null, "message": "草稿存储服务暂不可用"}
```

模型最终明确说“草稿未能保存，M04 目前没有排期”，并建议稍后重试或更换素材，没有返回成功状态或虚构 `draft_id`。

## 4. `case_normal` 首轮“请求用户确认”的重跑记录

`normal` 首轮使用的输入是：

```text
请帮我看下素材 M01 排期到 19:00
```

首轮真实 trace 为：

```text
read_material → check_rules → query_slots
```

模型确认 M01 审核通过、19:00-19:30 空闲，但没有调用 `save_draft`，而是回复：

> 按规则，保存草稿需要你确认最终时段……确认无误的话，我就保存这条排期草稿。要现在保存吗？

这不是模型失败，而是 `save_draft` 描述中的确认边界在起作用：用户只说了“排期到 19:00”，没有明确确认保存。为了覆盖“正常排期并保存”的验收点，输入被改成：

```text
素材 M01 就按 19:00-19:30 排，我已经确认这个时段，帮我保存草稿
```

重跑后模型走完：

```text
read_material → check_rules → query_slots → save_draft → 最终回答
```

`case_normal.md` 记录的是重跑后的真实过程。这个调整只改变了用户输入的明确程度，没有改 Agent、工具或模型逻辑。

## 5. `save_fail` 评估器误判的修正记录

`save_fail` 第一次真实运行中，模型输出本身是正确的：

> M04 的草稿没有保存成功……连续两次都返回「草稿存储服务暂不可用」。

但评估脚本第一次把“没有保存成功”中的子串“保存成功”误判成了成功声明，导致 AC-09 被判为未命中。问题出在评估器的关键词判断，不在模型或工具。

修正方式：

- 识别“保存成功”“已保存”等正向词时，同时排除“没有保存成功”“未保存成功”“未能保存”“保存失败”等否定表达；
- 重新运行 `save_fail` 真实 API 路径；
- 修正后判定为命中，`case_save_fail.md` 保留的是重跑后的真实失败链路。

这次修正没有改 `src/agent.py`、`src/tools.py` 或模型返回内容，只修了评估器的判定逻辑。它提醒我们：评估器本身也需要被验证，不能把自动判定当作绝对事实。

## 6. 结果汇总与证据边界

六个场景最终均为“命中”。对应验收点：

| 场景 | 主要验收点 |
| --- | --- |
| normal | AC-01 |
| conflict | AC-05、AC-11 |
| duplicate | AC-08 |
| missing | AC-02 |
| rule | AC-03 |
| save_fail | AC-09 |

需要诚实说明的证据边界：

- 最终 case 每个场景只保留一次最终运行（duplicate 为两次提交）；normal 和 save_fail 各因措辞或评估器问题重跑过一次，不能视为多次独立采样；
- DeepSeek 输出具有随机性，换时间或换模型版本可能得到不同措辞或不同工具顺序；
- `case_normal` 的首轮未保存被保留为过程记录，最终 case 使用明确确认后的重跑；
- `save_fail` 使用合成素材 M04 的强制失败标记，用于稳定覆盖存储失败分支；
- 评估结论是“这六条真实运行路径可复现、可解释”，不是“所有自然语言输入都能得到相同结果”。

## 7. 复现方式

配置 `.env` 中的 `DEEPSEEK_API_KEY` 后，可逐条复现：

```bash
python -m src.run_eval normal
python -m src.run_eval conflict
python -m src.run_eval duplicate
python -m src.run_eval missing
python -m src.run_eval rule
python -m src.run_eval save_fail
```

每次运行会覆盖对应的 `examples/case_<scenario>.md`，并打印 case 路径、运行状态、工具顺序和总体判定。

回归测试不需要真实 Key：

```bash
python -m pytest tests/ -v
```

当前结果：9 passed（3 条 ReAct 骨架测试 + 6 条场景回归测试）。回归测试使用 MockLLM 和固定合成数据，验证的是循环、工具契约和关键决策结果，不替代真实 API 评估。
