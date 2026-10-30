## 保存失败（save_fail）

> 生成方式：真实 DeepSeek API / `ReActAgent` / `TOOLS`。
> 模型：`deepseek-chat`；max_steps=8；生成时间：2026-10-30T03:54:20Z。
> 对照：[docs/01-requirements.md](../docs/01-requirements.md) （AC-09）。

### 输入

```text
素材 M04 排 19:00，帮我保存
```

### 运行过程 trace

| step | tool | arguments | result_summary | next_action |
| --- | --- | --- | --- | --- |
| 1 | read_material | {"material_id":"M04"} | {"success": true, "data": {"material_id": "M04", "title": "故障测试素材", "owner": "小陈", "category": "video", "duration_minutes": 4, "content": "用于验证草稿保存失败场景。", "_force_save_failure": true, "required_fields": ["title", "owner", "category", "duration_minutes"], "has_all_required_fields": true, "missing_... | continue |
| 1 | check_rules | {"material_id":"M04"} | {"success": true, "data": {"passed": true, "risk_level": "ok", "risk_reasons": [], "material_id": "M04"}, "message": "未命中风险规则"} | continue |
| 1 | query_slots | {"start_time":"19:00","end_time":"19:30"} | {"success": true, "data": {"available_slots": ["19:00-19:30"], "range": "19:00-19:30", "slot_minutes": 30}, "message": "查询完成，可用时段 1 个"} | continue |
| 2 | save_draft | {"material_id":"M04","slot":"19:00-19:30"} | {"success": false, "data": null, "message": "草稿存储服务暂不可用"} | continue |
| 3 | save_draft | {"material_id":"M04","slot":"19:00-19:30"} | {"success": false, "data": null, "message": "草稿存储服务暂不可用"} | continue |
| 4 | - | {} | **草稿未能保存，M04 目前没有排期。** 已完成的检查（均正常）： - 素材信息：M04《故障测试素材》，owner 小陈，category video，时长 4 分钟，必填字段齐全 - 审核结果：通过，风险等级 ok，无风险原因 - 时段查询：19:00-19:30 可用 失败原因：调用 `save_draft` 两次均返回「草稿存储服务暂不可用」，属于存储服务端故障，不是素材或时段的问题。值得注意的是，该素材内容标注为「用于验证草稿保存失败场景」，并带有强制保存失败的标记，因此这个失败很可能是该素材的预期行为。 建议： 1. 稍后重试保存，或等存储服务恢复后再排； 2. 如果这是... | finish |

### 模型最终输出

```text
**草稿未能保存，M04 目前没有排期。**

已完成的检查（均正常）：
- 素材信息：M04《故障测试素材》，owner 小陈，category video，时长 4 分钟，必填字段齐全
- 审核结果：通过，风险等级 ok，无风险原因
- 时段查询：19:00-19:30 可用

失败原因：调用 `save_draft` 两次均返回「草稿存储服务暂不可用」，属于存储服务端故障，不是素材或时段的问题。值得注意的是，该素材内容标注为「用于验证草稿保存失败场景」，并带有强制保存失败的标记，因此这个失败很可能是该素材的预期行为。

建议：
1. 稍后重试保存，或等存储服务恢复后再排；
2. 如果这是测试素材，请换用正式素材排期；
3. 需要的话，我可以帮你查一下 19:00 前后其他可用时段，或先为其他素材排期。

请告诉我下一步怎么处理。
```

### 导出状态

- 运行状态 `finished`，结束原因 `final_answer`，trace 4 步，工具顺序：read_material → check_rules → query_slots → save_draft → save_draft。
- 草稿文件：`data/drafts.json`，当前 0 条。
- 导出文件：`examples/case_save_fail.md`。

### 结果判定

| 验收点 | 判定 | 依据 |
| --- | --- | --- |
| AC-09 save_draft 返回失败 | 命中 | save_failed=True, message='草稿存储服务暂不可用', final_feedback=True, false_success=False |

**总体判定：命中**
