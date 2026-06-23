# Reviewer Prompt Templates

## 快速复核

请作为副 agent 复核这个 Antibubble Case。你不需要改代码，只根据看板指标和输出图判断结果可信度。

输入：

- Case: `<case_id>`
- 输出目录: `<output_dir>`
- 核心指标: `<metrics_json>`
- 可视化图: `group_meeting_final_four_panel.png`, `valid_window_tracking_preview.png`, `tracking_preview.png`

请输出：

```json
{
  "reviewer_score": 0,
  "pass": false,
  "confidence": "low|medium|high",
  "failure_reasons": [],
  "recommended_next_action": "",
  "main_agent_patch_request": {
    "parameter_changes": {},
    "code_changes_needed": []
  }
}
```

## 经验准则追加

我作为实验者新增一条经验准则：

`<写你的判断，例如：如果目标在有效帧后半段贴近 ROI 下边缘，则即使 tracking ratio 为 1，也要扣分。>`

请把这条准则转成：

- 可观察指标。
- 看板上应增加的字段。
- 副 agent 评分中应该调整的权重。
- 主 agent 下一轮需要保存的中间产物。

## 参数搜索复核

下面是同一个 Case 的多个处理版本，请按可信度排序，解释前三名为什么更好，并给出下一轮参数搜索范围。

输入：

`<runs_json>`

输出：

```json
{
  "ranking": [],
  "best_run_id": "",
  "why_best": "",
  "next_search_space": {},
  "stop_or_continue": "stop|continue"
}
```
