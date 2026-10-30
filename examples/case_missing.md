## 素材信息不足（missing）

> 生成方式：真实 DeepSeek API / `ReActAgent` / `TOOLS`。
> 模型：`deepseek-chat`；max_steps=8；生成时间：2026-10-30T03:53:43Z。
> 对照：[docs/01-requirements.md](../docs/01-requirements.md) （AC-02）。

### 输入

```text
素材 M02 需要排期，帮我看看
```

### 运行过程 trace

| step | tool | arguments | result_summary | next_action |
| --- | --- | --- | --- | --- |
| 1 | read_material | {"material_id":"M02"} | {"success": true, "data": {"material_id": "M02", "title": "未命名素材", "duration_minutes": 5, "content": "这是一条待补充信息的素材。", "required_fields": ["title", "owner", "category", "duration_minutes"], "has_all_required_fields": false, "missing_fields": ["owner", "category"]}, "message": "素材读取成功"} | continue |
| 1 | check_rules | {"material_id":"M02"} | {"success": true, "data": {"passed": false, "risk_level": "confirm", "risk_reasons": ["素材信息不完整，缺少字段：owner、category"], "material_id": "M02"}, "message": "命中风险规则，需处理"} | continue |
| 2 | - | {} | M02 目前还不能排期，有两个问题： **1. 素材信息不完整** - 标题：未命名素材（建议补一个正式标题） - 时长：5 分钟 - 缺失字段：**owner（负责人）**、**category（分类）** **2. 审核未通过** - 风险等级：`confirm`（需处理） - 原因：素材信息不完整，缺少 owner、category **下一步建议：** 请先补齐 M02 的 **owner** 和 **category**（最好也把标题改成正式名称），信息完整后我会重新跑一次审核。审核通过后，请告诉我你希望发布的时段范围（例如 18:00-20:00），我再查询可用时段并和你确认... | finish |

### 模型最终输出

```text
M02 目前还不能排期，有两个问题：

**1. 素材信息不完整**
- 标题：未命名素材（建议补一个正式标题）
- 时长：5 分钟
- 缺失字段：**owner（负责人）**、**category（分类）**

**2. 审核未通过**
- 风险等级：`confirm`（需处理）
- 原因：素材信息不完整，缺少 owner、category

**下一步建议：**
请先补齐 M02 的 **owner** 和 **category**（最好也把标题改成正式名称），信息完整后我会重新跑一次审核。审核通过后，请告诉我你希望发布的时段范围（例如 18:00-20:00），我再查询可用时段并和你确认最终时段，然后保存草稿。

需要我现在先帮你查一下某个时间段的可用时段做参考吗？
```

### 导出状态

- 运行状态 `finished`，结束原因 `final_answer`，trace 2 步，工具顺序：read_material → check_rules。
- 草稿文件：`data/drafts.json`，当前 0 条。
- 导出文件：`examples/case_missing.md`。

### 结果判定

| 验收点 | 判定 | 依据 |
| --- | --- | --- |
| AC-02 缺少审核所需字段 | 命中 | missing_fields=['category', 'owner'], no_save=True, final_feedback=True |

**总体判定：命中**
