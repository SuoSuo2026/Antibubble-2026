# Antibubble 2026 — Project Index

> 反气泡 (Antibubble) 研究项目：PB法反气泡生成 + 硬质小球PB输运 | 论文撰写中

## Quick Start

```powershell
python run_dashboard.py          # 启动看板 → http://127.0.0.1:8765/dashboard/
python agent_loop.py --once      # 扫描并处理新数据
python quill_session_refresh.py  # 刷新 Quill + Eureka + 看板
```

## File Map by Function

### 论文撰写 (Paper Writing) 🖊️

| 文件 | 用途 |
|------|------|
| `paper_writer.py` | 论文撰写核心工具：加载上下文、保存section、编译稿件 |
| `manuscript_agent.py` | Quill — 自动生成4段PRL草稿、估算论文进度 |
| `.claude/skills/write-section.md` | `/write-section` — 撰写/重写论文section |
| `.claude/skills/paper-review.md` | `/paper-review` — 6维度审查论文section |
| `.claude/skills/paper-sync.md` | `/paper-sync` — 同步所有数据源 |
| `.claude/skills/paper-compile.md` | `/paper-compile` — 编译最终Manuscript_filled.tex |
| `.claude/settings.json` | Skills注册配置 |
| `agent_workspace/paper_sections/` | 5个section的.md和.tex文件 |
| `agent_workspace/review_reports/` | 审查报告 |
| `agent_workspace/writing_state.json` | 撰写进度状态 |
| `agent_workspace/prl_figure_index.json` | PRL论文插图索引 (Fig.1-4) |

### 智能体 (Agents) 🤖

| 文件 | Agent | 职责 |
|------|-------|------|
| `agent_loop.py` | **Sisyphus** | 主处理循环：监控 raw_data/、调度处理 |
| `franklin_memory.py` | **Franklin** | 质检评分、记忆与规则、复核建议 |
| `eureka_agent.py` | **Eureka** | 文献语料库、研究方向、Franklin规则 |
| `manuscript_agent.py` | **Quill** | 论文草稿生成、进度估计 |
| `quill_session_refresh.py` | **Quill Refresh** | 事件驱动的会话刷新 |

### 处理管线 (Processing Pipeline) 🔬

| 文件 | 用途 |
|------|------|
| `main.py` | 标准 Antibubble 处理路线 (tracking → analysis → vis) |
| `rigid_ball_processing.py` | 硬质小球处理路线 (圆检测 → 轨迹 → 拟合) |
| `tracking.py` | 运动追踪 (Sisyphus模块) |
| `analysis.py` | 运动学分析 (Sisyphus模块) |
| `visualization.py` | 可视化生成 (Sisyphus模块) |
| `video_export.py` | 视频导出 |
| `fit_acceleration_oscillation.py` | 加速度/振荡频率拟合 |

### 看板 (Dashboard) 📊

| 文件 | 用途 |
|------|------|
| `dashboard_builder.py` | 构建看板数据 JSON |
| `dashboard/dashboard_data.json` | 看板数据 (16 cases, 32 runs, paper sections) |
| `dashboard/index.html` | 看板前端 |
| `dashboard/app.js` | 看板逻辑 (总控台/展示/文献/数据/相图/文章撰写) |
| `dashboard/styles.css` | 看板样式 |
| `dashboard/assets/paper_figures/` | 论文插图 (102张从docx提取) |
| `run_dashboard.py` | 看板启动脚本 |

### 实验数据处理脚本 📁

| 文件 | 用途 |
|------|------|
| `process_0415_17star_MB_voyager.py` | 0415批次 MB voyager处理 |
| `process_0415_26star_DB_voyager.py` | 0415批次 DB voyager处理 |
| `process_0415_32star_insuff.py` | 0415批次 insufficient deformation处理 |
| `make_group_meeting_final_figures.py` | 组会终版图表生成 |

### 文献与数据 (Library) 📚

| 路径 | 内容 |
|------|------|
| `library/Manuscript.tex` | PRL LaTeX模板 (revtex4-2, aps, prl) |
| `library/Manuscript_filled.tex` | 编译后的完整稿件 (由/paper-compile生成) |
| `library/Paper Writing/` | 毕业论文docx/pdf + Results.xlsx |
| `library/paper_figures/` | 文献雷达图缓存 (84张DOI-based) |
| `library/manuscript/` | Quill参考稿件 |
| `library/zotero_live_export.bib` | Zotero BibTeX导出 (215条) |
| `library/zotero_digest.json` | Zotero摘要 (213条去重, 86条2020+) |
| `library/PB_液膜包覆输运_文献堆栈表.xlsx` | 文献堆栈表 |
| `library/液滴震荡_低耗散输运_实验理论文献堆栈表.xlsx` | 文献堆栈表 |

### 工作空间 (Agent Workspace) 💾

| 路径 | 内容 |
|------|------|
| `agent_workspace/thesis_text.json` | 毕业论文全文 (375段, UTF-8) |
| `agent_workspace/thesis_figure_map.json` | 论文图片→段落映射 |
| `agent_workspace/figure_registry.json` | 完整图片注册表 (49张有上下文) |
| `agent_workspace/prl_figure_index.json` | PRL论文插图索引 |
| `agent_workspace/eureka_corpus.json` | Eureka文献语料库 (178条) |
| `agent_workspace/eureka_profile.json` | Eureka配置与规则 |
| `agent_workspace/quill_session_state.json` | Quill会话状态 |
| `agent_workspace/quill_session_brief.md` | Quill刷新摘要 |
| `agent_workspace/daily_memo.md` | 每日备忘录 |
| `agent_workspace/workflow_phase_summary.md` | 工作流阶段性总结文档 |
| `agent_workspace/reviewer_profile.json` | Franklin评分配置 |
| `agent_workspace/franklin_memory.json` | Franklin记忆与规则 |

### 配置与入口 ⚙️

| 文件 | 用途 |
|------|------|
| `config.yaml` | 项目配置 |
| `config_loader.py` | 配置加载器 |
| `todolist.md` | 待办清单 |
| `CHANGELOG.md` | 变更记录 |
| `CLAUDE.md` | 📍 本文件 — 项目索引导航 |
| `structure.txt` | 项目结构说明 |
| `start_dashboard.bat` / `.ps1` | 看板启动快捷方式 |
| `start_agent_loop.bat` / `.ps1` | Agent Loop启动快捷方式 |

### 辅助工具 🔧

| 文件 | 用途 |
|------|------|
| `image_utils.py` | 图像处理工具 |
| `io_utils.py` | IO工具 |
| `paper_figure_fetcher.py` | 文献图片抓取 |
| `zotero_importer.py` | Zotero导入 |
| `zotero_plugin_bridge.py` | Zotero插件桥接 |
| `codex_visual_smoke_test.py` | 可视化冒烟测试 |
| `main_old.py` | 旧版main (存档) |

### 版本控制 (Git) 🔄

| 项目 | 详情 |
|------|------|
| **Remote** | `https://github.com/SuoSuo2026/Antibubble-2026.git` |
| **Branch** | `master` (main) |
| **Tags** | `v0.1-baseline` — 基线版本 (2026-06-23) |
| **规则** | `v0.2`, `v0.3`... 阶段里程碑; `paper-draft`, `paper-submit` 论文节点; `exp-0415-done` 实验批次 |

```powershell
# 常用 Git 命令
git status                          # 查看变更
git log --oneline -10               # 最近提交
git diff v0.1-baseline..HEAD        # 对比基线
git tag paper-draft                 # 标记论文初稿节点
```

**当前未提交变更** (2026-06-23):
- `dashboard/` — 论文section面板 + 图片画廊 (M)
- `dashboard_builder.py` — paper_sections + paper_figures数据 (M)
- `.claude/` — 4个Writing Skills + 配置 (new)
- `CLAUDE.md` — 项目索引 (new)
- `paper_writer.py` — 论文撰写工具 (new)
- `dashboard/assets/paper_figures/` — 102张论文插图 (new)
- `library/Paper Writing/` — 毕业论文 + 数据 (new)

**建议下一步**:
```powershell
git add -A
git commit -m "[feat] Writing Skills + paper sections + figure gallery"
git tag paper-draft-v0.1
git push origin master --tags
```

## Key Data Points

- **Cases**: 16 total, 12 processed, 4 paused
- **Top case**: 01_PP_freefall (score: 100)
- **Rigid ball**: PP, PMMA, PS, POM (freefall + multi)
- **0415 batch**: 液滴类 (MB/DB voyager, insuff, freefall, multi/collapse)
- **Experiments**: 199组 液滴-PB 实验 (thesis)
- **Literature**: 178条 Eureka + 213条 Zotero (86条 2020+)
- **Paper progress**: 5/5 sections drafted, 0/5 reviewed, ~3173 words

## Paper Writing Workflow

```
/paper-sync     → 刷新所有数据源
/write-section  → 撰写/重写 section
/paper-review   → 审查 section (6 dimensions)
     ↻ iterate until PASS
/paper-compile  → 编译 Manuscript_filled.tex
```

## Current PRL Figures

| Fig | Content | Source Files |
|-----|---------|-------------|
| Fig. 1 | Experimental setup & PB frame | figure_021.png, figure_023.png |
| Fig. 2 | Droplet-PB interaction stages & outcomes | figure_004.png, figure_003.png |
| Fig. 3 | We-Bo phase diagrams | figure_098.png, figure_093.png |
| Fig. 4 | t/t criterion & combined phase diagram | figure_071.png, figure_090.png |
