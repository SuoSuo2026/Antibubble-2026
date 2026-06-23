# Antibubble 项目待办清单

> 基于 2026-06-22 工作流阶段性总结生成  
> 最后更新：2026-06-22

---

## 🔴 紧急 / 阻塞

- [ ] **15_PMMA_multi 人工复核** — 有效窗口偏短（Franklin 72.6 分），需确认 ROI/有效帧是否需要进一步调整
- [ ] **0415 液滴批次激活** — `0415-26star_DB_voyager` 仍为 `seen_existing`，补写 intake 后可处理；`0415-20star_PB_to_DB_to_MB`、`0415-33_multi_and_multi_and_collapse` 处于 paused

---

## 🟡 高优先级

- [ ] **硬球物理事件标注** — 对已处理 rigid ball case 标注 passing / trapping / rebound / false tracking 事件标签
- [ ] **无量纲数相图** — 确认各材料流体参数后，加入 Re、We、Bo、Ca 维度到相图页
- [ ] **0415 已确认 case 跑自动化 pipeline** — `0415-11star_multi`、`0415-17star_MB_voyager`、`0415-32star_insuff`、`0415-42star_freefall` 已人工确认，可跑 antibubble 标准路线

---

## 🟢 中期优化

- [ ] **Franklin 自动调参** — 对低分 Case 自动搜索参数空间（ROI、smooth_window、fit_time_range），重跑 2-3 个候选版本，只推最高分到看板精选
- [ ] **Franklin 新规则沉淀** — 将近期积累的主观经验（如"左侧液体运动干扰""边界反光点误判"）转化为 `franklin_memory.py` 结构化规则
- [ ] **Zotero 未读文献消化** — 当前 164 篇未读 / 32 篇已读，可逐步推进 Eureka 文献覆盖
- [ ] **云同步看板** — 看板数据同步到 OneDrive/Notion 作为镜像层，本地保持独立运行

---

## 🔵 论文冲刺（目标 ≥75% → full draft consolidation）

- [ ] **Introduction 深化** — 从 framework text 向单一尖锐科学声明推进
- [ ] **Results 补充** — 加入 0415 液滴批次的对比分析结果
- [ ] **Methods 细化** — 补充 rigid_ball 路线的圆检测算法细节和参数选择依据
- [ ] **Conclusions 强化** — 在更多 interaction case 处理后，提炼明确的双模型物理结论
- [ ] **PRL 模板填充** — 将 `library/Manuscript.tex` 的 placeholder 替换为 Quill 生成的真实内容

---

## ⚪ 日常维护

- [ ] 每次打开 Codex 推进本项目后，先运行 `python quill_session_refresh.py`
- [ ] 实验日保持 `python agent_loop.py --poll-interval 15 --intake-mode prompt` 在后台
- [ ] 看板常开 `http://127.0.0.1:8765/dashboard/`，关注精选页变动
- [ ] 有新经验时运行 `python franklin_memory.py feedback --case-id <id> --label <label> --note "<note>"`
