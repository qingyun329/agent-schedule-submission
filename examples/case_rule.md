## 规则风险（rule）

> 生成方式：真实 DeepSeek API / `ReActAgent` / `TOOLS`。
> 模型：`deepseek-chat`；max_steps=8；生成时间：2026-10-30T03:53:52Z。
> 对照：[docs/01-requirements.md](../docs/01-requirements.md) （AC-03）。

### 输入

```text
素材 M03 需要排 18:00 发布
```

### 运行过程 trace

| step | tool | arguments | result_summary | next_action |
| --- | --- | --- | --- | --- |
| 1 | read_material | {"material_id":"M03"} | {"success": true, "data": {"material_id": "M03", "title": "这款产品100%治愈你的困扰", "owner": "小周", "category": "healthcare", "duration_minutes": 2, "content": "医疗健康类产品介绍。", "required_fields": ["title", "owner", "category", "duration_minutes"], "has_all_required_fields": true, "missing_fields": []}, "mess... | continue |
| 1 | check_rules | {"material_id":"M03"} | {"success": true, "data": {"passed": false, "risk_level": "block", "risk_reasons": ["标题或文案包含绝对化用语：100%、治愈", "医疗健康类需人工确认"], "material_id": "M03"}, "message": "命中风险规则，需处理"} | continue |
| 2 | query_slots | {"start_time":"18:00-19:00"} | {"success": true, "data": {"available_slots": ["18:30-19:00"], "range": "18:00-19:00", "slot_minutes": 30}, "message": "查询完成，可用时段 1 个"} | continue |
| 3 | - | {} | M03 目前**不能排期**，我没有保存草稿。情况如下： **素材信息（完整）** - 标题：这款产品100%治愈你的困扰 - 负责人：小周｜分类：healthcare（医疗健康）｜时长：2 分钟 **审核结果：未通过（block）** 1. 标题/文案包含绝对化用语：「100%」「治愈」 2. 医疗健康类内容需人工确认 **时段情况** - 18:00-18:30 已被占用，该时段内唯一可用的是 **18:30-19:00**。 **建议下一步** 1. 修改标题，去掉「100%」「治愈」等绝对化表述（例如改为「这款产品帮你缓解日常困扰」这类合规说法）； 2. 医疗健康类素材需由人工审... | finish |

### 模型最终输出

```text
M03 目前**不能排期**，我没有保存草稿。情况如下：

**素材信息（完整）**
- 标题：这款产品100%治愈你的困扰
- 负责人：小周｜分类：healthcare（医疗健康）｜时长：2 分钟

**审核结果：未通过（block）**
1. 标题/文案包含绝对化用语：「100%」「治愈」
2. 医疗健康类内容需人工确认

**时段情况**
- 18:00-18:30 已被占用，该时段内唯一可用的是 **18:30-19:00**。

**建议下一步**
1. 修改标题，去掉「100%」「治愈」等绝对化表述（例如改为「这款产品帮你缓解日常困扰」这类合规说法）；
2. 医疗健康类素材需由人工审核确认后再排期；
3. 修改并复审通过后，我可以按你确认的时段保存草稿——注意 18:00-18:30 不可用，可选 18:30-19:00，或告诉我其他时间范围我再查。

需要我在你改好标题后重新走一遍审核吗？
```

### 导出状态

- 运行状态 `finished`，结束原因 `final_answer`，trace 3 步，工具顺序：read_material → check_rules → query_slots。
- 草稿文件：`data/drafts.json`，当前 0 条。
- 导出文件：`examples/case_rule.md`。

### 结果判定

| 验收点 | 判定 | 依据 |
| --- | --- | --- |
| AC-03 规则风险拦截 | 命中 | risk_level='block', reasons='标题或文案包含绝对化用语：100%、治愈 医疗健康类需人工确认', no_save=True, final_feedback=True |

**总体判定：命中**
