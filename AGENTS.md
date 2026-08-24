# AGENTS.md · AI 课堂项目工作规范

> 本文件是本仓库 AI 辅助开发的**唯一事实源**，按 harness 三层范式组织：Scaffolding（静态约束）/ Runtime（工作纪律）/ Eval（验证）。任何 AI 工具（Claude Code、Cursor、Copilot、Codex、Windsurf 等）在本仓库工作前必须先读本文件。

## 项目是什么

个人本地部署的 AI 老师课堂：FastAPI(Python) 后端 + React(TS) 前端播放器，课件逐页 TTS 讲解 + 答疑 Agent 对话 + 复述检查点。主线服务作者本人学习，未来演化成对外 AI 课堂。

---

# 一、Scaffolding —— 开工前必读的静态约束

## 1.1 文档索引（本文件的展开）

- `docs/设计方案-v1.md` —— 产品设计总纲（四 Agent 架构、场景、路线）
- `docs/P1执行计划.md` —— P1 阶段任务 T1~T6 及验收标准（已完成）
- `docs/P1.5执行计划.md` —— **当前阶段**：答疑 agent 打磨(A1~A6) + AI 教室骨架(B0~B2)、课表四泳道、衍生机制
- `docs/项目结构与开发规范.md` —— 目录结构、分层、API/工具链/Git 规范
- `docs/agent设计.md` —— 五维 × 每个 agent 的设计图纸（P2 备课施工依据）

## 1.2 边界铁律（违反=返工）

1. `apps/api` 与 `apps/web` **互不 import**；唯一连接是 HTTP(SSE) + `packages/api-types` 生成产物
2. **跨语言不手写共享类型**：后端 FastAPI 导出 OpenAPI → `openapi-typescript` 生成 TS 类型，前端只 import 生成产物
3. 前端 feature 之间只 import 对方 `index.ts` 公共出口
4. 后端：router 薄（校验+调 service）；async 路由内禁止阻塞调用
5. 知识库目录（`/Users/zhangyu/CodeDevelopment/学习知识库`）**只读**
6. `samples/` 与 `docs/` 已定稿内容不擅改，要改先说明
7. **Agent 分层**：一个 harness + 多个循环——基础设施（`app/core/` + `app/agent/tools.py` + `trace`）共享一份；每个 agent 是其上装配了不同工具/prompt/终止条件的独立循环，平级放 `app/agent/`。禁止「一个大循环调度所有 agent」（各 agent 节拍不同），也禁止「每个 agent 自建 config/trace」（观测性碎裂）
8. **工具按 agent 精选装配**：工具实现可共处一地，但暴露给每个 agent 的工具清单（传给 LLM 的 `TOOLS`）必须一份份按需精选。专属工具只进主人的清单——如 `write_csl`/`run_tts` 只给备课，绝不给答疑（防越权改课件 + 防选择困难 + 省 token，即 ACI「动作空间精简」）。共享工具（`read_notes`/`web_search`）由各 agent 各自"点单"列入，不算重复

## 1.3 技术栈速查

| 端 | 技术 |
|---|---|
| 后端 | Python · FastAPI · uv · ruff · mypy strict · anthropic SDK（base_url 指智谱）· edge-tts（provider 抽象） |
| 前端 | React · Vite · TS strict · Tailwind v4 · shadcn/ui · reveal.js(@revealjs/react) · assistant-ui |
| 契约 | OpenAPI 生成 TS 类型；SSE 事件信封 `{type,data,id}` + 心跳 |
| Git | Conventional Commits；简化 GitHub Flow（main 小步提交） |

## 1.4 四象限协作协议

> 本文件本身即第四象限（赋能区）的解：把人类私有决策结构化投喂给 AI。接到任何任务，先判断落在哪个象限，按对应策略协作：

| 象限 | 本项目典型场景 | AI 协作策略 |
|---|---|---|
| **① 共识区**（人知+AI知） | 常规编码：标准 CRUD、lint、既有框架惯用法 | **直接干**——指令式执行，不展开讨论，不堆砌背景 |
| **② 学习区**（人不知+AI知） | 涉及作者不熟的技术（如 FastAPI/reveal 细节） | **导师模式**——产码同时用小段注释/说明讲清关键点，标出「值得追问」的点，不许只丢代码就走。**特例：`apps/api/app/agent/`（agent 循环）板块动手前必须先停下**，完整讲解设计思想（循环结构、工具定义与回填、上下文组装、终止条件各自的取舍），与人对齐后才能写代码 |
| **③ 共创区**（人不知+AI不知） | 无标准答案的设计决策（交互方案、CSL 字段取舍） | **碰撞模式**——给 2~3 个候选方案+各自 trade-off，明确标注不确定性，禁止假装有确定答案 |
| **④ 赋能区**（人知+AI不知） | 项目既定决策：设计方案、任务范围、编码偏好、进度 | **先读后做**——决策已写在文档里，读并遵守；禁止重新发明或悄悄更改已定决策 |

**判错象限=返工**：把④当③重新讨论、把③当①擅自拍板，都是事故。

---

# 二、Runtime —— 干活时的工作纪律

## 2.1 任务编号制（防跑偏，最高优先级）

1. 只做 `docs/P1执行计划.md` 中当前任务及其前置
2. **范围外的想法（新功能、优化、重构）→ 先提出，不动手**，由人决定是否纳入
3. 开工前自查：本次改动对应哪个 T 编号？验收标准是什么？
4. 不擅自引入新依赖/新框架/新抽象——需要时先说明理由征得同意

## 2.2 会话循环

```
读 AGENTS.md「当前状态」
  → 确认当前 T 编号
  → 判断任务落在哪个象限（§1.4）
  → 按象限策略执行
  → 完成后更新「当前状态」节 + commit
```

---

# 三、Eval —— 完成后的验证

## 3.1 提交前自查清单

- [ ] 改动在当前 T 的范围内？
- [ ] 文件放对目录？没违反边界铁律（§1.2）？
- [ ] API 类型来自生成产物而非手写？
- [ ] 象限判对了？（④没重新讨论、③没擅自拍板）
- [ ] 通过 lint（ruff / eslint）？
- [ ] commit message 符合 Conventional Commits？

## 3.2 当前状态（每完成一个任务更新本节）

- 阶段：**P1.5（答疑 agent 打磨 + AI 教室骨架）** ← 策略改为垂直深耕：一个 agent 打磨成熟再做下一个
- ✅ P1 代码全部完成（T1~T6，2026-08-20）：CSL schema + 第一课（7页/27句/3检查点）、TTS 音频、reveal 课件渲染 + 三主题、音画同步引擎 + 断点续播 + 字幕、答疑 Agent 工具循环 + SSE、复述批改闭环
- ✅ P1 后续修复（2026-08-21）：音画时序按句首触发（with_sentence）、暂停原地续放、reveal 主题覆盖、对比度、右侧常驻对话栏、LLM 客户端工厂、上下文缓存名实相符、MAX_TURNS 软着陆、60s 超时、.env 自动加载、**答疑真流式 + markdown 渲染 + 与播放解耦**、窄框排版约束、输入框空格守卫
- ✅ **P1.5 全部完成（2026-08-21）→ 封版转 P2**:A1 总验收、A3 trace结构化+Eval接口（`410db00`）、B0 路由+B2 观测页（`f5955f0`）、A2 记忆+A5 会话（`7bb70b6`）、A4 引用可点（`a0bb3a5`）、B1 课表四泳道（`53edeae`，浏览器实测）、A6 答案自评（`dcd59ff` + 审查跟进）。答疑 agent 五维（工具/prompt/循环/记忆/观测）打磨闭环 + AI 教室骨架齐活;B1、A6 均过 reviewer
- ▶️ **下一阶段:P2 备课管线**（见 `docs/设计方案-v1.md`）;开工前先清下方收尾待办
- ✅ 收尾已清(2026-08-24):gen-types 管线接上(catalog `59f15bc` + sessions `89b8ac1`;csl.ts 经决策保持手写——稳定的作者态契约,理由注记在文件头)、A4 多页可点(`5349427`)、B2 显示自评瞎编率(`6ecd5be`)、traces/ 移出 git(`05a0c2d`)。**P1/P1.5 收口完成**
- ⚠️ 长期记账(不阻塞 P2):①A4/ChatPanel 的 typescript-reviewer 屡被中转挡,恢复后补(现以 §3.1 自查+浏览器实测代替);②A6 局限:伪造「课件第N页」假引用会绕过自评 → `self_eval_fabricated` 是下限;③dev 服务器(API :8100 / web :5173)会话结束需重启

---

## 常用命令（代码初始化后生效）

```bash
make dev        # 同时起前后端
make lint       # ruff + eslint
make gen-types  # OpenAPI → packages/api-types
```

## AI 工具差异说明

- **Claude Code**：详见 `CLAUDE.md`（子 Agent 调用约定）
- 其他工具：遵守本文件；审查用 §3.1 清单代替
