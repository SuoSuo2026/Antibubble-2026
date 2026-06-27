# Antibubble 2026 — Project Index

> 反气泡 (Antibubble) 研究项目：PB法反气泡生成 + 硬质小球PB输运 | 论文撰写中
> 最后更新：2026-06-25 | 最新提交：`430c705`

## Quick Start

```powershell
python run_dashboard.py          # 启动看板 → http://127.0.0.1:8765/dashboard/
python agent_loop.py --once      # 扫描并处理新数据
python quill_session_refresh.py  # 刷新 Quill + Eureka + 看板
```

## 论文理论框架 (Theory Framework) 🔬

> 核心创新：**PB中液滴与硬球的平行输运**，通过双线对照分离"PB几何贡献（通用）"与"液滴变形贡献（专用）"。

### 三条判据

| # | 判据 | 公式 | 控制阶段 | 状态 |
|---|------|------|---------|------|
| 1 | **We-Bo 能量准则** | We + 2Bo = C₁, C₁ = 0.038±0.004 | Stage 2: 进入 PB | ✅ 完整 (199实验) |
| 2 | **t_p/t_d 排水准则** | t_p/t_d < 1 | Stage 2→3: pinch-off 存活 | ⚠️ ε ~ 10 μm 为估算 |
| 3 | **Collapse 数 C** | C ≡ α³ × f × t_trans / (V_p/V_f) | Stage 3: PB 中输运 | ⚠️ V_p, ε₀ 待测量 |

### 耦合 PB 液膜–液滴振荡模型

- **n=2 Lamb 模态体积守恒** (∫∫Y_{2m} dΩ = 0) → 振荡高度可逆 → 循环充放（非 RC 衰减）
- 气膜极硬 (k_gas/k_cap ~ 10⁶) → 锁定 PB 液膜与液滴表面
- 压力均衡 τ_eq ~ 0.1 ms ≪ T_osc ~ 15 ms → 空间均匀
- ε_min ≈ 0.98 ε₀ → 远在范德华破裂阈值之上
- **振荡主导重力**：τ_g/t_trans ~ 24, v_osc/v_g ~ 5.5

### 结构化数据文件

| 文件 | 内容 |
|------|------|
| `agent_workspace/theory_framework.json` | 完整理论框架：3条判据 + 耦合模型 + 振荡数据 + 实验计划 |
| `library/Supplementary_Material.tex` | 理论附录 S1-S7：全部推导 + 无量纲表 + 数据表 |

---

## 待完成 (Pending Tasks) ⚠️

### 🔴 阻塞项 — 需要接入原始数据

| 任务 | 说明 | 方法 |
|------|------|------|
| **Outcome 标注** | 0415 批次所有 case 需分类：packing / outer coalescence / inner coalescence | 从 .tif 原始文件肉眼判断 pinch-off 前后几帧 |
| **气囊体积 V_p 提取** | pinch-off 后液滴上方的亮区面积 → 球冠模型 → V_pocket | 方案 D：亮度阈值分割（现有图像 31 μm/px，气囊 ~10-30 px 可分辨） |
| **We, Bo 计算** | 各 case 的 We, Bo 值（dashboard 中全为 null） | 从 tracking 速度差分得到 v₀，代入 We = ρv₀²(2R)/σ |
| **ε₀ 推估** | 从 V_pocket 追踪 + 气体守恒反推初始气膜厚度 | V_gas = V_p + 4πR²ε₀，短期溶解可忽略 |
| **Collapse 数 C 标定** | 用 collapse case 和 packing case 分别计算 C，确定 C_crit | 需要以上所有数据 |

### 🟡 高优先级 — 理论可做

| 任务 | 说明 | 状态 |
|------|------|------|
| Lamb 频率理论对标 | 用 n=2, n=3 Lamb 公式计算 f_theory vs f_measured (60-69 Hz) | 📋 已有参数，半天 |
| δR/R vs outcome 相关性 | 比较 collapse 和 packing 的振荡振幅 | 📋 需 outcome 标注后 |
| 耦合模态完整求解 | PB 三角棱柱几何中的 normal-mode analysis | 🔮 下一篇论文 |

### 🟢 可选 — 实验验证

| 任务 | 说明 |
|------|------|
| 干涉法 ε 测量（方案 B） | 需要搭光路（532 nm 激光 + 扩束），精度 ~0.5 μm |
| 染色实验（3-14） | 硬球表面染色 → 判断 PB 输运中气膜存在性 |

---

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
| `agent_workspace/theory_framework.json` | 🆕 结构化理论框架数据 |
| `library/Overleaf_Package/` | 🆕 Overleaf 排版包：main.tex + SM.tex + 8 figures + .bib |
| `library/Supplementary_Material.tex` | 🆕 完整理论附录 S1-S7 |

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
| `dashboard_builder.py` | 构建看板数据 JSON（含 theory_framework 数据源） |
| `dashboard/dashboard_data.json` | 看板数据 (16 cases, 32 runs, paper sections, theory_framework) |
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
| `library/Overleaf_Package/main.tex` | 🆕 完整稿件（官方模板，含 5 图 + 全部引用） |
| `library/Overleaf_Package/Supplementary_Material.tex` | 🆕 理论附录 S1-S7 |
| `library/Overleaf_Package/figures/` | 🆕 8 张 PRL 插图（PNG） |
| `library/Overleaf_Package/references.bib` | 🆕 修复版 BibTeX（补全 commereuc 条目） |
| `library/Supplementary_Material.tex` | 🆕 理论附录（主副本） |
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
| `agent_workspace/theory_framework.json` | 🆕 结构化理论框架：判据 + 耦合模型 + 实验计划 |
| `agent_workspace/thesis_text.json` | 毕业论文全文 (375段, UTF-8) |
| `agent_workspace/thesis_figure_map.json` | 论文图片→段落映射 |
| `agent_workspace/figure_registry.json` | 完整图片注册表 (49张有上下文) |
| `agent_workspace/prl_figure_index.json` | PRL论文插图索引 |
| `agent_workspace/eureka_corpus.json` | Eureka文献语料库 (178条) |
| `agent_workspace/eureka_profile.json` | Eureka配置与规则 |
| `agent_workspace/quill_session_state.json` | Quill会话状态 |
| `agent_workspace/quill_session_brief.md` | Quill刷新摘要（含 2026-06-25 理论进展） |
| `agent_workspace/daily_memo.md` | 每日备忘录 |
| `agent_workspace/workflow_phase_summary.md` | 工作流阶段性总结文档 |
| `agent_workspace/reviewer_profile.json` | Franklin评分配置 |
| `agent_workspace/franklin_memory.json` | Franklin记忆与规则 |
| `agent_workspace/paper_sections/` | 5个section的.md和.tex文件 |
| `agent_workspace/review_reports/` | 审查报告 |
| `agent_workspace/writing_state.json` | 撰写进度 + theory_framework + pending_experiments |

### 配置与入口 ⚙️

| 文件 | 用途 |
|------|------|
| `config.yaml` | 项目配置 |
| `config_loader.py` | 配置加载器 |
| `todolist.md` | 待办清单（含原始数据接入任务） |
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
| **Latest Commit** | `430c705` — `[feat] Complete theory framework: parallel transport, coupled oscillation model, collapse number` |
| **Tags** | `v0.1-baseline` — 基线版本 (2026-06-23) |
| **规则** | `v0.2`, `v0.3`... 阶段里程碑; `paper-draft`, `paper-submit` 论文节点; `exp-0415-done` 实验批次 |

```powershell
# 常用 Git 命令
git status                          # 查看变更
git log --oneline -10               # 最近提交
git diff v0.1-baseline..HEAD        # 对比基线
git tag paper-draft                 # 标记论文初稿节点
```

## Key Data Points

- **Cases**: 16 total, 12 processed, 4 paused
- **Top case**: 01_PP_freefall (score: 100)
- **Rigid ball**: PP, PMMA, PS, POM (freefall + multi)
- **0415 batch**: 液滴类 (MB/DB voyager, insuff, freefall, multi/collapse)
- **Experiments**: 199组 液滴-PB 实验 (thesis)
- **Literature**: 178条 Eureka + 213条 Zotero (86条 2020+)
- **Paper progress**: 5/5 sections drafted, 理论框架已结构化, Overleaf 包已就绪

### 液滴振荡数据

| Case | R (mm) | f (Hz) | δR/R (%) | Outcome |
|------|--------|--------|----------|---------|
| 0415-42star_freefall | 2.035 | 60.6±0.4 | 3.9 | ❓待标注 |
| 0415-11star_multi | 1.936 | 68.6±0.7 | 3.3 | ❓待标注 |
| 0415-17star_MB | 2.331 | 62.1±1.3 | 3.3 | ❓待标注 |
| 0415-26star_DB | 2.007 | — | — | ❓待标注 |
| 0415-32star_insuff | 1.701 | — | — | insufficient (18帧) |

## Paper Writing Workflow

```
/paper-sync     → 刷新所有数据源
/write-section  → 撰写/重写 section
/paper-review   → 审查 section (6 dimensions)
     ↻ iterate until PASS
/paper-compile  → 编译 Manuscript_filled.tex
```

## Current PRL Figures (Overleaf Package)

| Fig | Content | File |
|-----|---------|------|
| Fig. 1 | Experimental setup & PB frame | fig1_setup_a.png, fig1_setup_b.png |
| Fig. 2 | Droplet-PB interaction stages & outcomes | fig2_stages.png, fig2_outcomes.png |
| Fig. 3 | We-Bo phase diagrams | fig3_webo_atm.png, fig3_webo_vacuum.png |
| Fig. 4 | t/t criterion & combined phase diagram | fig4_combined.png, fig4_schematic.png |
| Fig. 5 (planned) | Droplet vs rigid-sphere oscillation comparison | TBD |

## 给新 Claude 对话的上下文摘要

当开启新对话处理本项目时，请先阅读：
1. **`agent_workspace/theory_framework.json`** — 获取完整理论框架和实验计划
2. **`agent_workspace/quill_session_brief.md`** — 获取最新进展摘要
3. **`todolist.md`** — 获取当前待办清单
4. **本文件** — 获取项目全貌

当前最紧急的待完成事项是：**接入原始 .tif 数据 → Outcome 标注 → V_pocket 提取 → We/Bo 计算 → ε₀ 推估 → Collapse 数 C 标定**。
