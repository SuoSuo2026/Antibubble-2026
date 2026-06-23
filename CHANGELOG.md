# Changelog

> Antibubble 项目重要变更记录 —— 方便回退与检查

---

## v0.1-baseline (2026-06-23)

- 项目首次纳入版本控制
- 核心分析管线完整：tracking → analysis → visualization
- 0415 液滴批次处理脚本就绪（MB/DB/insuff）
- Rigid ball 实验处理路线 working
- 看板系统上线（dashboard）
- 论文 Manuscript.tex + Zotero 文献库完整
- 文献图库 80+ 篇关键文献截图

---

## 使用方式

| 场景 | 操作 |
|------|------|
| 查看变更历史 | `git log --oneline` 或 [GitHub Commits](https://github.com/SuoSuo2026/Antibubble-2026/commits/master) |
| 回退到基线 | `git checkout v0.1-baseline` |
| 对比两个版本 | `git diff v0.1-baseline..HEAD` 或 [GitHub Compare](https://github.com/SuoSuo2026/Antibubble-2026/compare) |
| 查看某个 tag 的代码 | `git checkout <tag>` |
| 回到最新代码 | `git checkout master` |

---

## 标签规则

| 标签格式 | 含义 |
|----------|------|
| `v0.1-baseline` | 基线版本 |
| `v0.2`、`v0.3` ... | 阶段性里程碑 |
| `paper-draft`、`paper-submit` | 论文关键节点 |
| `exp-0415-done` | 实验批次完成 |
