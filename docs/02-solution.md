# 解决方案与设计说明

## 1. 设计目标

本项目要解决的不是“生成一段排期文案”，而是让 Agent 在一次可观察的 ReAct 过程中完成以下决策链：

1. 读取指定素材，确认信息是否完整；
2. 按审核规则判断素材是否存在风险；
3. 查询目标时段是否与已有排期冲突；
4. 在满足规则和确认条件后保存草稿；
5. 如果信息不足、存在风险、发生冲突或保存失败，如实告知用户，不越权操作。

设计遵循三条原则：

- **模型负责决策，工具负责事实。** 工具不根据素材编号写死“下一步该做什么”，只返回素材、规则、时段和保存结果；是否继续、是否保存由模型结合 observation 决定。
- **写操作只到草稿。** 项目没有真实发布工具，`save_draft` 只写 `data/drafts.json`。
- **确认是硬边界。** 冲突改期、硬性发布时间调整等动作，必须先获得用户明确确认；当前原型通过系统提示、工具描述和受控运行约束实现，生产环境需在存储层增加可校验的确认记录（见 6.5）。

## 2. 整体架构

```text
CLI / demo_tools / run_eval
            │
            ▼
   ReActAgent（src/agent.py）
   system + user messages + trace
            │
            │ chat(messages, TOOLS)
            ▼
 DeepSeekLLM / MockLLM（src/llm.py）
            │
            │ tool_calls
            ▼
 TOOLS 注册表（src/tools.py）
 read_material / check_rules / query_slots / save_draft
            │
            │ observation
            ▼
 追加 role=tool 消息 → 下一轮循环
            │
            │ 无 tool_calls
            ▼
        最终回答
```

### 2.1 组件职责

| 组件 | 职责 |
| --- | --- |
| `src/cli.py` | 命令行入口；读取环境变量，决定使用 DeepSeek 还是 MockLLM；注入 `TOOLS` 并运行 Agent |
| `src/agent.py` | ReAct 循环；维护 messages/trace；执行工具；把 observation 回填；处理 `max_steps` |
| `src/llm.py` | `DeepSeekLLM` 负责 OpenAI 兼容接口调用；`MockLLM` 负责离线脚本化回放 |
| `src/tools.py` | 四个业务工具及 `TOOLS` 注册表；统一返回 `success/data/message` |
| `data/` | 素材、规则、排期和运行时草稿 |
| `examples/` | 真实 DeepSeek API 运行产生的评估记录 |
| `tests/` | ReAct 骨架测试与六条场景回归测试 |

### 2.2 一次完整调用链

1. CLI 读取用户输入，构造 `ReActAgent(llm, tools=TOOLS, max_steps=8)`。
2. Agent 初始化 `system` 和 `user` 消息，进入循环。
3. LLM 返回 `LLMResponse`：可能是最终文本，也可能是若干 `tool_calls`。
4. 如果有工具调用，Agent 先写入 assistant 的 `tool_calls` 消息，再逐个执行工具。
5. 每个工具结果被转换为字符串 observation，写入 `role=tool` 消息；trace 同时记录步骤号、工具名、参数、结果摘要和 `next_action`。
6. 下一轮把包含 observation 的完整 messages 再交给 LLM，直到模型不再返回工具调用。
7. 模型直接返回文本时，循环结束并把该文本作为最终回答；若到达 `max_steps` 仍有工具调用，返回 `{"status": "unfinished", "reason": "max_steps"}`。

## 3. 四个业务工具的数据流

四个工具都返回统一结构：

```json
{"success": true, "data": {}, "message": "..."}
```

失败时 `data` 为 `null`，`message` 说明原因。工具不抛出业务异常；未预期的异常也会被兜底成失败结果，由 Agent 作为 observation 回填给模型。

| 工具 | 读取 | 写入 | 核心输出 |
| --- | --- | --- | --- |
| `read_material` | `data/materials.json` | 无 | 素材字段 + `required_fields` + `has_all_required_fields` + `missing_fields` |
| `check_rules` | `data/materials.json`、`data/rules.json` | 无 | `passed`、`risk_level`、`risk_reasons`、`material_id` |
| `query_slots` | `data/schedule.json` | 无 | `available_slots`、查询范围、30 分钟粒度 |
| `save_draft` | `data/materials.json`、`data/drafts.json` | `data/drafts.json` | `draft_id`、`duplicate`、素材与时段 |

### 3.1 `read_material`

- 按 `material_id` 读取素材列表；
- 必填字段固定为 `title`、`owner`、`category`、`duration_minutes`；
- 对空字符串、`null` 和空容器统一视为缺失；
- 在素材原始字段之外追加 `required_fields`、`has_all_required_fields`、`missing_fields`；
- 找不到素材时返回 `success=false`，`message="素材不存在"`；
- 只读，不修改 `materials.json`。

M02 就是通过这条路径暴露 `owner` 和 `category` 缺失，模型再决定暂停排期并要求补充。

### 3.2 `check_rules`

- 先调用 `read_material`，复用同一套完整性判断；
- 读取 `data/rules.json`，逐条匹配；
- 支持两类规则：
  - `keyword_any`：在指定字段（`title`、`content`）中匹配关键词；
  - `field_equals`：字段值与规则值相等；
- 命中 `rule_001` 时返回绝对化用语及具体命中词；
- 命中 `rule_002` 时返回“医疗健康类需人工确认”；
- 风险等级按 `block > confirm > ok` 聚合；
- 素材缺字段时以 `confirm` 返回，并将缺失字段写入 `risk_reasons`；
- 只读，不保存草稿，不做“遇到 M03 就拒绝”的硬编码。

### 3.3 `query_slots`

- 支持 `query_slots("18:00-20:00")`，也兼容 `start_time`/`end_time` 分开传入；
- 只接受 30 分钟对齐的 `HH:MM-HH:MM`；
- 读取 `data/schedule.json` 的 `occupied` 列表；
- 按 30 分钟切片生成候选时段，排除与已占用区间重叠的时段；
- 返回 `available_slots`，例如占用 `18:00-18:30` 时返回：

```text
["18:30-19:00", "19:00-19:30", "19:30-20:00"]
```

- 只读，不自动占用或修改排期。

### 3.4 `save_draft`

- 先确认素材存在；
- 如果素材带 `_force_save_failure=true`（M04），始终返回失败，`message="草稿存储服务暂不可用"`；
- 校验 `slot` 必须是 30 分钟时段；
- 以 `material_id + slot` 作为唯一键：
  - 首次保存生成 `draft_xxx`，`duplicate=false`；
  - 相同键再次保存返回已有 `draft_id`，`duplicate=true`；
- 新草稿写入 `data/drafts.json`，文件不存在时自动创建；
- 通过临时文件加替换的方式写入，避免留下半截 JSON；
- 不调用任何真实发布接口。

## 4. ReAct 循环的终止条件与 `max_steps`

### 4.1 正常终止

LLM 返回的 `tool_calls` 为空时，Agent 视为模型已经给出最终回答：

- 把最终回答写入 trace，`tool=null`，`next_action="finish"`；
- 返回最终回答字符串；
- 不强制要求模型再调用任何工具。

### 4.2 到达 `max_steps`

每次工具执行后会检查当前步骤。如果已经到达 `max_steps` 且模型仍要求调用工具：

- 不再发起下一轮 LLM 调用；
- 返回 `{"status": "unfinished", "reason": "max_steps"}`；
- 最后一个工具 trace 的 `next_action` 标记为 `max_steps`；
- 不会伪造“已完成”或“已保存”。

### 4.3 工具异常

工具执行失败、参数不合法、工具不存在或工具函数抛异常时，Agent 捕获异常并把错误文本作为 observation 回填，循环继续。模型可以看到失败原因并决定重试、换工具或向用户说明。

### 4.4 `max_steps` 取值

默认值为 8。当前最长路径是“读取 → 审核 → 查询 → 保存 → 最终回答”，通常在 4 步左右完成；8 步为模型的重试、补充查询和错误恢复留出空间。该值不是业务规则，而是防止无限循环的安全阀；更长链路可以在调用方调高，但应同时考虑超时、成本和模型失控风险。

## 5. 与 AC-01 至 AC-12 的覆盖关系

编号严格对应 [01-requirements.md](01-requirements.md) 的验收点。

| 验收点 | 覆盖方式 | 证据与说明 |
| --- | --- | --- |
| AC-01 正常素材 + 空闲时段 | 已验证 | `case_normal.md`：读取 M01、审核通过、19:00-19:30 空闲、保存成功并返回 `draft_id` |
| AC-02 缺少审核所需字段 | 已验证 | `case_missing.md`：M02 缺 `owner`、`category`，模型要求补充，未保存 |
| AC-03 规则风险拦截 | 已验证 | `case_rule.md`：M03 命中 `block`，给出“100%”“治愈”等原因，未保存 |
| AC-04 规则风险人工确认 | 实现覆盖 | `check_rules` 能返回 `confirm`；模型按 observation 请求人工确认。未单独构造只有 `confirm` 的 case |
| AC-05 时段冲突 | 已验证 | `case_conflict.md`：发现 18:00-18:30 被占，给出 18:30-19:00，要求确认，未保存 |
| AC-06 冲突后拒绝替代方案 | 设计覆盖 | 工具层不会自动改期；没有用户确认时 Agent 不调用保存。未单独跑“用户拒绝”对话 |
| AC-07 冲突后确认替代时段 | 设计覆盖 | 保存只在明确确认后发生；未单独跑“确认后保存”对话，正常路径可复用该机制 |
| AC-08 重复提交 | 已验证 | `case_duplicate.md`：第二次 `duplicate=true`，沿用同一 `draft_id`，草稿 1 条 |
| AC-09 `save_draft` 失败 | 已验证 | `case_save_fail.md`：两次失败均返回“草稿存储服务暂不可用”，未产生草稿 |
| AC-10 全流程检查 | 已验证 | 所有 case 均无真实发布动作；每个 case 都包含 trace、最终回答和导出状态 |
| AC-11 硬性发布要求保护 | 已验证/设计覆盖 | 冲突 case 未在确认前改期保存；工具不修改硬性要求 |
| AC-12 确认有效性 | 设计覆盖 | 保存动作只由模型在对话确认后发起；未把模糊确认自动化成保存 |

说明：AC-04、AC-06、AC-07、AC-12 不是没有实现，而是当前六条真实 API case 没有分别构造独立对话。它们由 Agent 的确认边界和 `save_draft` 的“只写草稿”机制覆盖；如果要做更严格的验收，应补充这四类交互 case。

## 6. 关键设计取舍

### 6.1 为什么不在工具里写业务分支

如果 `check_rules` 里写“M03 就返回什么”，或 `save_draft` 里写“看到 M01 就保存”，系统就只是在执行固定脚本，无法证明模型具备决策能力。当前实现只返回事实：

- M03 的风险来自 `rules.json` 的关键词和分类；
- 是否保存由模型读取 observation 后决定；
- 工具不知道“第几步该调用谁”。

### 6.2 为什么把幂等放在 `save_draft`

重复提交是存储层的确定性问题，不应依赖模型“记得不要重复保存”。因此唯一键和 `duplicate` 判断放在工具层；即使模型重复调用，也只会得到同一份草稿。

### 6.3 为什么 trace 要独立记录

`agent.messages` 适合模型消费，但不适合评审阅读。`agent.trace` 只保留 step、tool、arguments、result_summary、next_action，既能证明循环真实发生，也避免把完整上下文和潜在敏感信息写入案例文件。

### 6.4 为什么只保存草稿

真实发布涉及渠道授权、审核责任和不可逆操作。当前项目把写操作限制在本地 `drafts.json`，用最小风险验证“审核 + 排期 + 确认”的决策链。

### 6.5 确认机制的当前边界

当前“用户确认”是对话层约束：Agent 的系统提示和 `save_draft` 的工具描述要求模型在明确确认后才保存，冲突场景也不会自动改期。但工具层没有独立的确认令牌、用户身份或审批单号，`save_draft` 本身无法证明“调用前一定发生过确认”。

这在当前六条受控 case 中成立，但生产环境应把确认结构化：保存时携带 `approval_id` 或确认记录，服务端校验确认对象（素材 + 最终时段）和有效期，避免仅依赖模型自觉。
