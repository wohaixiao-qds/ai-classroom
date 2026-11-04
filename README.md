# AI 课堂（ai-classroom）

本地部署的私有 AI 老师：给它一个想学的主题，它自动**调研 → 规划大纲 → 逐课生成书页式课程**（文字 + mermaid 插图 + 检查点 + 闪卡），你按大纲点单学习；课堂内嵌答疑 Agent 与复述批改，学完自动蒸馏笔记写回 Obsidian 知识库，检查点/闪卡按间隔重复排期复习。

## 功能一览

- 🔍 **大纲调研**：输入主题，agent 搜索资料产出零基础完整学习路线（篇章 + 先修链 + 每课可验证目标）
- 📚 **课程生成**：按大纲逐课点单备课，agent 写出 v2 书页课件（节/块结构，检查点 pass_rule 可判，备课全程可观测）
- 📖 **书页阅读器**：TOC / 滚动断点 / 深链；检查点复述 → LLM 百分制批改（<70 打回重述，≥70 判过），「问 AI 老师」联动多轮答疑
- 🔁 **间隔复习**：检查点与闪卡按 [1,3,7,14,30,60] 天排期（低置信封顶：一次蒙对不算过），学习台到期提醒
- 📝 **知识沉淀**：学完打卡 → 三源蒸馏 → 确认写回 Obsidian vault（vault 目录结构跟随大纲自动同步）
- 🧠 **答疑 Agent**：认识全库课程与你的学习进度，跨课融通；SSE 真流式 + 工具调用（联网搜索/读笔记）

## 技术栈

FastAPI（Python 3.12+）· React 19 + Vite + TS strict + Tailwind v4 + shadcn/ui · SQLite · LLM 走智谱 Anthropic 兼容端点（默认 glm-5.3，可换 Claude/Z.ai）

## 快速开始

前置：[uv](https://docs.astral.sh/uv/)、[pnpm](https://pnpm.io/)、Node 18+、Python 3.12+

```bash
git clone <本仓库> && cd ai-classroom
pnpm install

# 配置密钥（唯一必须手动做的一步）
cp config/secrets.env.example config/secrets.env
# 编辑 config/secrets.env,填入 ZHIPU_API_KEY(必填)

./start.sh    # 起 API(:8100) + 前端(:5273),日志在 .run/
```

打开 http://localhost:5273 → **生成中心** → 「我想学」输入一个主题 → 调研出课程大纲 → 自动备第一门样课 → 到课程库开读。

> clone 下来课程库是空的：课件与学习数据属个人内容，已 gitignore 不入库。所有课程用生成中心现生成（走 LLM，一门约 15 分钟，消耗 tokens）。

## 密钥与配置

全部配置集中在 `config/secrets.env`（已 gitignore，绝不入库），模板见 `config/secrets.env.example`：

| 变量 | 必填 | 说明 |
|---|---|---|
| `ZHIPU_API_KEY` | ✅ | LLM key（[open.bigmodel.cn](https://open.bigmodel.cn) → API Keys） |
| `LLM_MODEL` | ❌ | 默认 `glm-5.3`，可换 `glm-4.6` 等 |
| `LLM_BASE_URL` | ❌ | 默认智谱国内站 Anthropic 兼容端点，可换 Claude / Z.ai |
| `SEARCH_API_KEY` | ❌ | 博查搜索（[open.bochaai.com](https://open.bochaai.com)），不填则答疑不联网 |
| `TAVILY_API_KEY` | ❌ | Tavily 搜索（[tavily.com](https://tavily.com)），三源兜底之一 |
| `ANYSEARCH_API_KEY` | ❌ | AnySearch（[anysearch.com](https://www.anysearch.com/)），匿名亦可 |
| `KB_DIR` | ❌ | Obsidian vault 目录（知识沉淀写回用；目录不存在则写回功能不可用，其余不受影响） |

## 目录结构

```
├── apps/api     # FastAPI 后端:app/agent(各 agent 循环) · app/core(基础设施) · app/services
├── apps/web     # React 前端:features/(页面模块) · src/types(OpenAPI 生成类型,已入库)
├── config/      # 密钥配置(secrets.env 已 gitignore)
├── docs/        # 设计方案 / 各阶段执行计划 / 竞品拆解
└── samples/     # 定稿样例
```

## 开发

```bash
./start.sh api|web          # 单独重启一端
uv run --directory apps/api ruff check app   # 后端 lint
pnpm -C apps/web lint                        # 前端 lint
pnpm -C apps/web gen-types                  # 后端改 API 后重新生成 TS 类型(需 API 已启动)
```

AI 辅助开发规范见 [AGENTS.md](AGENTS.md)，产品设计文档见 [docs/](docs/)。
