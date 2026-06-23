# Antibubble 项目工作流阶段性总结

> 生成日期：2026-06-22  
> 数据来源：dashboard_data.json、agent_loop_state.json、quill_session_state.json、eureka_profile.json、reviewer_profile.json  
> 状态：看板最后一次刷新于 2026-06-18；Agent Loop 最后一次处理于 2026-05-28

---

## 一、项目概览

本项目研究**反气泡 (antibubble) 及硬质小球在 Plateau 边界/液膜网络中的输运行为**。通过高速摄影 TIFF 堆栈 → 自动跟踪 → 运动学分析 → 多 Agent 协作审阅 → Web 看板展示，构建了一条从原始数据到论文草稿的半自动化流水线。

### 当前数据规模

| 指标 | 数值 |
|---|---|
| 总 Case 数 | **16** |
| 处理运行数 | **32** (同一 Case 可有多个参数版本) |
| 已处理 Case | **12** |
| 暂停 Case | **4** |
| 看板精选 Case (≥75分) | **10** |
| 最高分 Case | **01_PP_freefall** |
| 文献库去重条目 | **213** (Zotero)，其中 2020+ 文献 **86** 条，含 DOI **179** 条，本地 PDF **212** 篇 |
| 论文完成度 | **63%** — "results-driven drafting" 阶段 |

---

## 二、四 Agent 协作架构

```
┌──────────────────────────────────────────────────────────────┐
│                    Sisyphus (主 Agent)                        │
│  agent_loop.py — 文件监控 + 处理调度 + 看板刷新               │
│  · 轮询 raw_data/ 中新增 .tif，15s 间隔                        │
│  · 通过 intake 门控收集主观经验（prompt / file / off 三种模式） │
│  · 自动识别 rigid_ball vs antibubble 实验类型，切换处理路线     │
│  · 调度 tracking → analysis → visualization → video export    │
│  · 处理完毕触发 Franklin 审阅，刷新看板数据                     │
└──────────────┬───────────────────────────────────────────────┘
               │ 产出 metrics + 预览图 + 视频
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌──────────────────────────────────────┐
│Franklin│ │Eureka  │ │Quill (论文撰写 Agent)                 │
│审阅评分│ │文献校验│ │manuscript_agent.py                    │
│        │ │        │ │· 区分 rigid/droplet 实验类型          │
│franklin│ │eureka_ │ │· 生成 PRL/JFM 风格四段草稿            │
│_memory │ │agent.py│ │  (Introduction / Methods /            │
│.py     │ │        │ │   Results / Conclusions)              │
│        │ │        │ │· 策略：只写已完成内容，未知留白         │
│打分+   │ │文献语料│ │· 论文进度 63%，novelty: medium-high    │
│flag+   │ │交叉验证│ │quill_session_refresh.py               │
│记忆+   │ │白名单  │ │· 事件驱动会话刷新                       │
│建议    │ │调整评分│ │· 触发 Zotero 导出 + 看板重建            │
└───┬────┘ └───┬────┘ └──────────────────────────────────────┘
    │          │
    └────┬─────┘
         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Dashboard (Web 看板)                         │
│  dashboard/ — http://127.0.0.1:8765/dashboard/               │
│  首页「精选」(≥75分) + 「全部」双视图                          │
│  含：Case 列表、评分、flag、文献雷达、论文进度、会话刷新摘要    │
└─────────────────────────────────────────────────────────────┘
```

### 各 Agent 边界与权限

| Agent | 职责 | 能做 | 不能做 |
|---|---|---|---|
| **Sisyphus** | 数据处理 | 读 TIFF、跑 pipeline、写输出、刷新看板 | 不擅自改算法参数 |
| **Franklin** | 质量审阅 | 读主 Agent 输出，按规则打分+flag+建议 | 不直接修改处理代码 |
| **Eureka** | 文献观察 | 读文献库，独立总结现象方向，通过白名单规则影响 Franklin 评分 | 不把文献方法直接改成 pipeline；不读 Zotero 原始数据 |
| **Quill** | 论文撰写 | 根据已完成结果生成草稿，吸收旧论文风格 | 不编造未完成内容；不把旧论文结论当新事实 |

---

## 三、处理流水线

### 3.1 数据入站

1. 新 `.tif` 放入 `raw_data/`
2. Sisyphus 检测到新文件 → 根据 `intake_mode` 触发经验收集：
   - `prompt`：终端交互式问卷（输入主观经验、实验类型、参数 → 输入 `PROCESS` 开始）
   - `file`：生成 `intake/<case_id>.json` 模板，等人工设 `ready_to_process: true`
   - `off`：完全自动，不等人
   - 支持 `FAST` 模式：直接继承上一个 rigid_ball case 的参数（FPS、pixel_per_mm）
3. `ready_to_process == true` → 调度处理

### 3.2 双路线处理

**Rigid Ball 路线**（`rigid_ball_processing.py`）：
- 适用：硬质固体小球（PP、PMMA、PS、POM），材料从文件名自动检测
- 圆检测 → xy 轨迹 → y-t 抛物线拟合 → 速度/反弹事件
- 不使用液滴振荡频率

**Antibubble 路线**（`main.py` 标准 pipeline）：
- 适用：液滴/包覆体
- tracking → kinematics (smoothing, velocity, acceleration) → advanced analysis (quadratic fit, FFT, oscillation fit, harmonic fit) → visualization → video export

### 3.3 审阅评分

Franklin 按 `reviewer_profile.json` 权重打分：

| 维度 | 权重 | 优秀阈值 | 差阈值 |
|---|---|---|---|
| tracking (valid_found_ratio) | 25% | — | — |
| radius_stability (radius_rel_std) | 25% | ≤2.0% | ≥8.0% |
| fit_stability (a_fit 跨窗口一致性) | 30% | ≤0.5% | ≥3.0% |
| frequency_stability (oscillation freq) | 20% | ≤1.0% | ≥5.0% |

评分后经 **Eureka 文献一致性调整** 和 **Franklin 记忆匹配调整**，最终输出：
- `band`: `excellent` / `usable_review` / `needs_review`
- `flags`: 如 `radius_unstable`, `short_valid_window`, `eureka_rigid_particle_mode`
- `recommended_next_action`: 下一步建议

---

## 四、实验数据集一览

### 4.1 Rigid Ball — 自由落体 (freefall)

| Case | 材料 | 最高分 | Band | a_fit (mm/s²) | radius_rel_std |
|---|---|---|---|---|---|
| 01_PP_freefall | PP | **100** | excellent | −9721 | 0.58% |
| 02_PMMA_freefall | PMMA | **100** | excellent | −9395 | 1.73% |
| 03_PS_freefall | PS | **100** | excellent | −8646 | 1.47% |
| 04_POM_freefall | POM | **100** | excellent | −9616 | 1.49% |

> 四个 freefall 案例全部满分。半径极稳定（<2%），加速度接近自由落体（~−9600 mm/s²），PS 略低可能与密度/空气阻力有关。

### 4.2 Rigid Ball — 多球/复杂场景 (multi)

| Case | 材料 | 初始分 | 优化分 | 初始问题 | 优化措施 |
|---|---|---|---|---|---|
| 10_POM_multi | POM | 56.0 | **100** | radius_unstable (87%) | 切换保守 ROI/Vfr |
| 15_PMMA_multi | PMMA | 56.0 | **72.6** | radius_unstable (134%) | 切换保守 ROI/Vfr；有效窗口仍偏短 |
| 20_PP_multi | PP | 62.6 | **100** | short_valid_window | 切换保守 ROI/Vfr |

> multi 场景的主要挑战是左侧液体运动和边界反光点干扰。通过切换到更保守的 ROI 和有效帧窗口（`_roi_guard` / `_focus_cosine` 版本），大部分 case 恢复到了满分。15_PMMA_multi 的有效窗口仍然较短（72.6 分），建议人工复核。

### 4.3 Antibubble 液滴类 (0415 exhibition)

| Case | 状态 |
|---|---|
| 0415-11star_multi | confirmed（人工确认） |
| 0415-17star_MB_voyager | confirmed |
| 0415-26star_DB_voyager | seen_existing（待处理） |
| 0415-32star_insuff | confirmed |
| 0415-42star_freefall | confirmed |
| 0415-20star_PB_to_DB_to_MB | paused |
| 0415-33_multi_and_multi_and_collapse | paused |
| 0407-2 | paused |

> 0415 批次包含 MB voyager（单液滴长程输运）、DB voyager、PB→DB→MB 相变、multi 碰撞、freefall 等丰富现象。目前以人工确认为主，多数尚未跑自动化 pipeline。

---

## 五、文献与论文状态

### 5.1 Eureka 文献库

| 指标 | 数值 |
|---|---|
| 文献栈源文件 | `PB_液膜包覆输运_文献堆栈表.xlsx`、`液滴震荡_低耗散输运_实验理论文献堆栈表.xlsx` |
| Zotero 去重条目 | 213 |
| 2020+ 文献 | 86 |
| 含 DOI | 179 |
| 本地 PDF | 212 |
| 已读 / 未读 / 混合 | 32 / 164 / 17 |

**Top 5 主题簇**：

1. droplet_impact_transport (75 篇)
2. rigid_particles_interfaces (56 篇)
3. liquid_film_measurement (55 篇)
4. antibubble_core (55 篇)
5. plateau_border_foam (若干)

### 5.2 Quill 论文进度：63%

| 维度 | 得分 | 满分 |
|---|---|---|
| 数据覆盖 | 22.8 | 25 |
| 文献支撑 | 14.6 | 20 |
| 撰写完成 | 14.0 | 20 |
| 创新性 | 12 | — |
| **合计** | **63** | ~100 |

**当前阶段**：`results-driven drafting`（结果驱动起草）

**已完成的四个 Section**：

- ✅ Introduction — 文献地图 + 区分 rigid/droplet 研究动机
- ✅ Experimental Methods — Sisyphus/Franklin/Eureka 工作流 + 双路线说明
- ✅ Results — 7 个 rigid 案例 + 6 个 droplet 案例的高层总结
- ✅ Conclusions — 双模型动机 + 无量纲数拓展方向

**Quill 策略**：所有草稿只包含看板中已完成并经过 Franklin 评分的数据。未知机制、未测量参数、未确认现象一律留白（`Insufficient evidence; left blank for now.`）。

---

## 六、当前工作流待办

### 短期（已标记）

1. **15_PMMA_multi 人工复核**：有效窗口较短（72.6 分），需确认是否需要进一步调整 ROI
2. **0415 液滴批次激活**：多个 case 仍为 `seen_existing` 或 `paused`，可补充 intake 后批量处理
3. **硬球物理事件标注**：确认 passing / trapping / rebound / false tracking 的事件标签
4. **无量纲数相图**：确认流体参数后加入 Re、We、Bo、Ca 维度

### 中期（架构）

1. **Franklin 自动调参**：对低分 Case 自动搜索参数空间，重跑 2-3 个候选版本，只推最高分到精选
2. **Quill 草稿深化**：从 framework text 向更尖锐的单一科学声明推进
3. **云同步**：看板数据同步到 OneDrive/Notion 作为镜像层

### 长期（论文冲刺）

- 论文完成度从 63% 推进到 ≥75%（full draft consolidation）
- 补充更多 interaction cases（小球-液膜/PB 相互作用）
- 将现有 PRL 模板的 placeholder 替换为真实数据

---

## 七、关键技术参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| FPS | 2000 | 高速摄影帧率 |
| pixel_per_mm | ~25.53 | 标定系数（可通过 intake 覆盖） |
| ROI | x=0, y=100, w=1920, h=360 | 默认感兴趣区域 |
| smooth_window | 9 | 运动学平滑窗口 |
| quad_fit_time_range | [0.035, 0.085] s | 二次拟合时间窗 |
| freq_scan_range | [20, 80] Hz | 振荡频率扫描范围 |
| featured_min_score | 75 | 看板精选阈值 |
| poll_interval | 15 s | Agent Loop 扫描间隔 |

---

## 八、运行命令速查

```powershell
# 启动看板
python run_dashboard.py

# 启动 Agent Loop（交互式 intake）
python agent_loop.py --poll-interval 15 --intake-mode prompt

# 一次性扫描处理
python agent_loop.py --once --process-existing --intake-mode off

# Quill 会话刷新
python quill_session_refresh.py

# Franklin 记忆查询
python franklin_memory.py show

# 硬球单次处理
python rigid_ball_processing.py --tiff "raw_data/<file>.tif" --output-dir "processed_data/..." --roi 0,80,1920,500 --fps 2000 --pixel-per-mm 25.5333

# 看板地址
# http://127.0.0.1:8765/dashboard/
```
