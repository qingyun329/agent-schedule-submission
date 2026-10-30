## 重复提交（duplicate）

> 生成方式：真实 DeepSeek API / `ReActAgent` / `TOOLS`。
> 模型：`deepseek-chat`；max_steps=8；生成时间：2026-10-30T03:53:34Z。
> 对照：[docs/01-requirements.md](../docs/01-requirements.md) （AC-08）。

### 输入

```text
素材 M01 就按 19:00-19:30 排，我已经确认这个时段，帮我保存草稿
```

### 运行过程 trace

#### 第 1 次提交

| step | tool | arguments | result_summary | next_action |
| --- | --- | --- | --- | --- |
| 1 | read_material | {"material_id":"M01"} | {"success": true, "data": {"material_id": "M01", "title": "新品开箱视频", "owner": "小林", "category": "video", "duration_minutes": 3, "content": "全新产品开箱，展示外观、配件和上手体验。", "required_fields": ["title", "owner", "category", "duration_minutes"], "has_all_required_fields": true, "missing_fields": []}, "message... | continue |
| 1 | check_rules | {"material_id":"M01"} | {"success": true, "data": {"passed": true, "risk_level": "ok", "risk_reasons": [], "material_id": "M01"}, "message": "未命中风险规则"} | continue |
| 2 | query_slots | {"start_time":"19:00-19:30"} | {"success": true, "data": {"available_slots": ["19:00-19:30"], "range": "19:00-19:30", "slot_minutes": 30}, "message": "查询完成，可用时段 1 个"} | continue |
| 3 | save_draft | {"material_id":"M01","slot":"19:00-19:30","notes":"用户已确认时段"} | {"success": true, "data": {"draft_id": "draft_bbe0f2dccc5f", "duplicate": false, "material_id": "M01", "slot": "19:00-19:30"}, "message": "草稿保存成功"} | continue |
| 4 | - | {} | 草稿已保存成功 ✅ - **素材**：M01《新品开箱视频》（owner：小林，类型：video，时长 3 分钟） - **审核**：通过，风险等级 ok，无风险原因 - **时段**：19:00-19:30（已确认可用） - **草稿 ID**：draft_bbe0f2dccc5f 注意：这只是草稿，尚未真实发布。 | finish |

#### 第 2 次提交

| step | tool | arguments | result_summary | next_action |
| --- | --- | --- | --- | --- |
| 1 | read_material | {"material_id":"M01"} | {"success": true, "data": {"material_id": "M01", "title": "新品开箱视频", "owner": "小林", "category": "video", "duration_minutes": 3, "content": "全新产品开箱，展示外观、配件和上手体验。", "required_fields": ["title", "owner", "category", "duration_minutes"], "has_all_required_fields": true, "missing_fields": []}, "message... | continue |
| 1 | check_rules | {"material_id":"M01"} | {"success": true, "data": {"passed": true, "risk_level": "ok", "risk_reasons": [], "material_id": "M01"}, "message": "未命中风险规则"} | continue |
| 2 | save_draft | {"material_id":"M01","slot":"19:00-19:30","notes":"用户已确认时段"} | {"success": true, "data": {"draft_id": "draft_bbe0f2dccc5f", "duplicate": true, "material_id": "M01", "slot": "19:00-19:30"}, "message": "相同素材和时段已存在草稿，未重复创建"} | continue |
| 3 | - | {} | 草稿已就绪 ✅ - **素材**：M01《新品开箱视频》（owner：小林，类型：video，时长 3 分钟） - **信息完整性**：title、owner、category、duration_minutes 均齐全 - **审核结果**：通过，风险等级 ok，未命中风险规则 - **时段**：19:00-19:30 - **草稿 ID**：draft_bbe0f2dccc5f 说明：系统提示该素材与时段**已存在相同草稿**，因此未重复创建，返回的是已有草稿。这只是草稿，尚未真实发布。 | finish |

### 模型最终输出

#### 第 1 次提交

```text
草稿已保存成功 ✅

- **素材**：M01《新品开箱视频》（owner：小林，类型：video，时长 3 分钟）
- **审核**：通过，风险等级 ok，无风险原因
- **时段**：19:00-19:30（已确认可用）
- **草稿 ID**：draft_bbe0f2dccc5f

注意：这只是草稿，尚未真实发布。
```
#### 第 2 次提交

```text
草稿已就绪 ✅

- **素材**：M01《新品开箱视频》（owner：小林，类型：video，时长 3 分钟）
- **信息完整性**：title、owner、category、duration_minutes 均齐全
- **审核结果**：通过，风险等级 ok，未命中风险规则
- **时段**：19:00-19:30
- **草稿 ID**：draft_bbe0f2dccc5f

说明：系统提示该素材与时段**已存在相同草稿**，因此未重复创建，返回的是已有草稿。这只是草稿，尚未真实发布。
```

### 导出状态

- 第 1 次：运行状态 `finished`，结束原因 `final_answer`，trace 4 步，工具顺序：read_material → check_rules → query_slots → save_draft。
- 第 2 次：运行状态 `finished`，结束原因 `final_answer`，trace 3 步，工具顺序：read_material → check_rules → save_draft。
- 草稿文件：`data/drafts.json`，当前 1 条。
- 导出文件：`examples/case_duplicate.md`。

### 结果判定

| 验收点 | 判定 | 依据 |
| --- | --- | --- |
| AC-08 相同素材 + 相同最终时段重复提交 | 命中 | first_duplicate=False, second_duplicate=True, same_draft_id=True, draft_count=1, final_feedback=True |

**总体判定：命中**
