# CLAUDE.md

本仓库的 AI 开发规范**唯一事实源是根目录 `AGENTS.md`**——先读它并遵守其全部纪律（任务编号制、边界铁律、提交前自查）。

以下仅为 Claude Code 的专属补充：

## 子 Agent 约定

- **审查**：改动涉及 `apps/api` 用 `ecc:python-reviewer`，涉及 `apps/web` 用 `ecc:typescript-reviewer`；两者皆涉及则各跑一次
- **任务拆解**：大任务用 `ecc:planner`
- **范围守门**：开工前对照 `docs/P1执行计划.md` 确认任务编号；范围外想法按 AGENTS.md 纪律 1 处理——提出，不动手

## 会话约定

- 会话开始：读 `AGENTS.md` → 确认当前 T 编号 → 干活
- 每完成一个任务：更新 `AGENTS.md` 的「当前状态」节 + 对应 commit
