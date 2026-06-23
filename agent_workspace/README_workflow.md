# Antibubble Agent Workflow

这个文件夹是“主 agent / Franklin 副 reviewer / 看板”的本地协作层。第一版目标不是替代你的实验判断，而是把判断显式化、可重复化，并让网页不再需要你手动翻文件夹。

## 1. 文件分工

- `processing_switches.json`: 看板上的处理开关。网页切换后会写回这里。
- `reviewer_profile.json`: Franklin 副 reviewer 的评分口味、权重、精选阈值。
- `case_registry.json`: 每个 Case 的 ROI、有效帧、fps 等长期配置覆盖。
- `intake/<case_id>.json`: 新数据进入后，处理前的主观经验输入表。
- `franklin_memory.json`: Franklin 的本地记忆，包括经验、结构化规则、人工反馈和待转规则提案。
- `agent_loop_state.json`: watcher 状态、处理状态、错误和复核建议。
- `reviewer_reports/<case_id>_latest.json`: Franklin 风格的最新复核报告。

## 2. 看板

启动：

```powershell
python run_dashboard.py
```

打开：

```text
http://127.0.0.1:8765/dashboard/
```

首页默认显示“精选”，只放达到 `reviewer_profile.json` 中 `dashboard_display.featured_min_score` 的结果。需要监管全量数据时，点“全部”。

## 2.1 Quill 会话刷新

推荐触发点不是每日固定时间，也不是开机，而是“你打开 Codex 并开始推进本项目后的第一轮动作”。此时先运行：

```powershell
python quill_session_refresh.py
```

它会做一个轻量、事件驱动的 refresh：

- 检查 `raw_data`、`processed_data`、`library`、manuscript 和看板数据是否变化。
- 有变化时刷新 Zotero 插件导出、`zotero_digest.json` 和 `dashboard_data.json`。
- 无实质变化时只写简短状态，不触发深度例会。
- 写入 `agent_workspace/quill_session_brief.md`，并显示在总控台“本次会话刷新”。

边界：Quill 只负责会话开场整理和论文进度语境；不自动修改处理算法，不自动覆盖已确认结果，不把文献方法直接改成 pipeline。

## 3. 自动循环

推荐启动方式：

```powershell
python agent_loop.py --poll-interval 15 --intake-mode prompt
```

也可以双击根目录的 `start_agent_loop.bat`。

模式说明：

- `--intake-mode prompt`: 新 `.tif` 进入后，在终端窗口问你主观经验，输入 `PROCESS` 后才处理。
- `--intake-mode file`: 新 `.tif` 进入后生成 `agent_workspace/intake/<case_id>.json`，你把 `ready_to_process` 改成 `true` 后才处理。
- `--intake-mode off`: 完全自动，不等人工经验。
- `--once`: 扫描一次就退出。
- `--process-existing`: 处理已经登记为 `seen_existing` 的旧文件，可能耗时很长。
- `--dry-run`: 只走队列和状态，不跑重处理。

## 4. 当前主 / 副 agent 边界

主 agent 负责：

- 读取 `.tif`
- 按配置跑 tracking、analysis、visualization、video export
- 写标准 JSON、图片和视频
- 刷新看板数据

Franklin 副 reviewer 负责：

- 只读主 agent 输出
- 根据 `reviewer_profile.json` 打分、加 flag、给下一轮建议
- 把高分结果推入看板“精选”

当前 Franklin 是本地规则化 reviewer。Codex 打开时，可以再让真实子 agent 做深度复核；Codex 关闭时，本地 loop 仍能按规则运行。

## 5. Franklin 自我更新

Franklin 现在有一个受控记忆层：

- 你在 intake 里输入的 `subjective_experience` 和 `review_criteria` 会写入 `franklin_memory.json`。
- 后续复核会显示命中了哪些旧经验、哪些结构化规则。
- 结构化规则可以自动修正分数，例如默认 ROI/默认有效帧会被扣分。
- 自由文本经验不会自动改分，只会成为上下文和待转规则提案，避免一句模糊经验污染评分体系。

查看记忆：

```powershell
python franklin_memory.py show
```

手动给 Franklin 反馈：

```powershell
python franklin_memory.py feedback --case-id 0415-26star_DB_voyager --label good --note "这类稳定半径曲线可信"
```

加入结构化规则：

```powershell
python franklin_memory.py add-rule --label "贴边扣分" --keyword "贴边" --score-adjustment -8 --recommendation "目标贴边时先缩小或移动 ROI 后重跑。"
```

## 6. 新数据进入时的推荐节奏

1. 保持 `agent_loop.py --intake-mode prompt` 运行。
2. 把新 `.tif` 放进 `raw_data`。
3. 终端会弹出输入问题。
4. 写入你对这个 Case 的经验，例如“后半段容易贴边”“有效帧大概 160-275”“不要相信频率”。
5. 输入 `PROCESS`，主 agent 开始处理。
6. 看板刷新，首页只显示高分精选结果。

## 7. 可复制升级 prompt

### 新经验固化

我新增一条经验准则：`<写你的判断>`。请把它转化为 Franklin 可评分字段，更新 `reviewer_profile.json` 或 `dashboard_builder.py`，并让看板显示对应 flag。

### 硬质刚体小球实验

今天的数据是硬质固体小球，不是液滴。请使用 `rigid_ball_processing.py` 路线，关注圆检测、半径稳定性、x/y 轨迹、y-t 抛物线拟合、速度和反弹事件，不要使用液滴振荡频率作为结论。

### 自动调参

请让 Franklin 对低分 Case 给出下一轮参数搜索空间，并让主 agent 自动重跑 2-3 个候选版本，只把最高分版本推到看板精选。

### 云同步

请把看板数据同步到 `<OneDrive/Google Drive/Notion/数据库>`。要求本地仍可独立运行，云端只作为镜像或共享层。
