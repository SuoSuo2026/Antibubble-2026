# Quill Session Brief — 2026-06-25

## 核心进展：理论框架重大更新

### 创新点重塑
**PB中液滴与硬球的平行输运。**
- PB 几何提供**通用**低阻力输运通道（液滴和硬球均可）
- 液滴可变形性赋予**专属**气膜夹带能力 → 反气泡生成
- 双线对照分离"几何贡献"与"变形贡献"
- 文献检索确认：目前没有 2024-2025 论文同时覆盖 PB + 液滴/颗粒输运 + 微流控（niche 未被占）

### 两条独立判据
1. **We-Bo 能量准则**（Stage 2, 进入 PB）：`We + 2Bo = C₁`, C₁ = 0.038 ± 0.004
   - 94% packing 分离准确率。PB 几何效率 ~2× 水平界面法（C₁' = 0.072）
2. **t_p/t_d 排水准则**（Stage 2→3, pinch-off 存活）：`t_p/t_d < 1`
   - 气膜润滑排水模型。ε ~ 10 μm 为估算值，测量待补
   - 解释 P < 0.3 atm 的气压依赖失效

### 耦合 PB 液膜–液滴振荡模型（新建）
- 气体压力均衡 τ_eq ~ 0.1 ms ≪ T_osc ~ 15 ms → P_gas 空间均匀
- PB 液膜惯性可忽略 (ρ_film δ_film / ρR ~ 5×10⁻⁴) → 准静态响应
- 气膜极硬 (k_gas/k_cap ~ 10⁶) → 锁定 PB 液膜与液滴表面
- **核心洞察**：n=2 Lamb 模态体积守恒 (∫∫Y_{2m} dΩ = 0)
  → 振荡高度可逆 → 解释气膜为何能存活上百周期
- ε_min ≈ 0.98 ε₀ → 远在范德华破裂阈值 (100 nm) 之上

### Collapse 机制（新建）
非 RC 衰减，而是**循环充放 + 慢泄漏**：
- h³ 整流效应：每周期 ~20% 净外向偏压
- 底部 triple-line 泄漏
- 气囊对称破缺

**Collapse 数**：`C ≡ α³ × f × t_trans / (V_p/V_f)`
- 硬球：α = 0 → C = 0 → 永不 collapse ✓

### 振荡 vs 重力
- τ_g ~ 2.4 s ≫ t_trans ~ 0.1 s → 重力来不及作用
- v_osc/v_g ~ 5.4 → 振荡主导气膜动力学

## 已有数据
| Case | R (mm) | f (Hz) | δR/R (%) |
|------|--------|--------|----------|
| 0415-42star_freefall | 2.035 | 60.6±0.4 | 3.9 |
| 0415-11star_multi | 1.936 | 68.6±0.7 | 3.3 |
| 0415-17star_MB | 2.331 | 62.1±1.3 | 3.3 |

## 待补（需原始数据接入）
1. Outcome 标注（packing/outer coalescence/inner coalescence）
2. 气囊体积 V_p 提取（方案 D：pinch-off 图像亮度分割）
3. ε₀ 从 V_pocket 追踪反推
4. 各 case 的 We, Bo 计算
5. Collapse 数 C 标定

## 文件更新
- `library/Overleaf_Package/main.tex` — 完整稿件
- `library/Overleaf_Package/Supplementary_Material.tex` — 理论附录
- `library/Overleaf_Package/figures/` — 8 张 PRL 插图
- `agent_workspace/theory_framework.json` — 结构化理论数据
