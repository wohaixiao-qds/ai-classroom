# UI 重设计 · 两区制规范（v2 定稿）

> 2026-11-24 用户依四张高保真稿拍板定稿。设计稿原件在 `design-preview/`（reader.html / library.html / classroom-panels.html / index.html），本文件是其向代码落地的唯一翻译依据。
> 核心拍板：**退役三主题切换器**（ThemeSwitcher），全站改为「两区固定色板」——阅读面永远纸感、工具面永远冷灰靛蓝。

## 一、两区制总纲

| 气质区 | 页面 | 设计语言 | 设计稿 |
|---|---|---|---|
| **阅读面（paper）** | `/read/:id` 阅读器三栏（目录/正文/答疑）+ 检查点弹层 + 划词提问 | 纸感：暖纸底、墨色文字、霞鹜文楷正文、赭石单强调、界面退后 | reader.html + classroom-panels.html |
| **工具面（tool）** | 课程库书架 `/courses`、书内目录 `/books/:topic`、详情页、生成中心 `/gen`、观测 `/eval`、Shell 导航 | 现代 SaaS：冷灰底、近黑文字、单一靛蓝强调、高密度、分层阴影 | library.html v2 |

实现机制：**`:root` 挂工具面色板（默认），`[data-zone="read"]` 挂纸面色板**——阅读器根容器设 `data-zone="read"`，其子树内所有 shadcn 语义变量自动切换为纸感值。语义变量名（`--color-primary` 等）保持不变，组件零改动换色。

## 二、色板（唯一事实源）

### 工具面（tool，挂 `:root`）

| 语义 | 值 | 说明 |
|---|---|---|
| bg | `#f6f6f8` | 页面底 + 双色 radial 光晕（indigo 5% 右上 / ok 3.5% 左下）+ SVG 细颗粒纸纹（opacity 0.5，见 design 库） |
| card | `#ffffff` | 卡面 |
| text | `#18181b` | 主文字 |
| text-muted | `#6f6f78` | 次级 |
| text-faint | `#a1a1aa` | 弱注/mono 注记 |
| line | `#e7e7ec` | 边框；line-2 `#f1f1f4` 分隔线 |
| accent (primary) | `#4655d4` | 靛蓝单强调；deep `#3340a8`（渐变用）；soft `#eef0fd` |
| ok | `#18915b` / soft `#e9f6ef` | 成功/已出/已学 |
| busy (warning) | `#b7791f` / soft `#faf3e3` | 备课中/到期 |

### 阅读面（paper，挂 `[data-zone="read"]`）

| 语义 | 值 | 说明 |
|---|---|---|
| bg | `#f4efe3` | 纸面底 |
| card | `#fdfbf3` | 正文纸/浮层纸 |
| text | `#33302a` | 墨 |
| text-muted | `#7a7263` | 淡墨 |
| text-faint | `#a49a86` | 极淡 |
| line | `#e4dcc8` | 纸纹线 |
| accent (primary) | `#b4532a` | 赭石；soft `#f3e2d6`（选中/用户气泡底） |
| ok | `#5b7a5e` | 已读 ✓ |
| warning | bg `#f5ead6` / line `#d8bd90` / ink `#8a6a35` | 坑 callout、打卡横幅 |

## 三、字体与排版

| 用途 | 栈 |
|---|---|
| UI（工具面全部 + 阅读面 chrome） | `-apple-system,"PingFang SC","Noto Sans SC",sans-serif` |
| 阅读正文（阅读面 prose） | `"LXGW WenKai","LXGW WenKai Lite","Kaiti SC","Songti SC",Georgia,serif`（现有 `--font-reading` 保持） |
| 数字/计数/mono 注记 | `"JetBrains Mono",ui-monospace,monospace`（已自托管） |

- 阅读正文：17.5px / 行高 1.95 / `letter-spacing:.012em` / 两端对齐（CLREQ 延续，现有 prose 微排版保留，只换色不换排版规则）
- UI 基准 13.5–14px；计数一律 `font-variant-numeric:tabular-nums`
- 书封书名：衬线栈（Noto Serif SC → Songti SC 回退）19px/1.45
- 标注性小字（区块头右注、mono 英文注记）：11px / `letter-spacing:.14em` / faint 色

## 四、形状与深度

- 圆角三档：控件 8–9px / 卡片 12–14px / 大卡与弹层 16px / 胶囊 999px
- 阴影两档（工具面）：`--shadow-1: 0 1px 2px rgba(20,20,30,.05), 0 2px 8px rgba(20,20,30,.04)`；`--shadow-2: 0 1px 2px rgba(20,20,30,.05), 0 10px 30px rgba(20,20,30,.09)`；卡片 hover 用 shadow-2 + `translateY(-2~-3px)`
- 书封立体投影：`inset 0 0 0 1px rgba(255,255,255,.08), 0 1px 2px rgba(20,20,30,.25), 0 10px 22px rgba(20,20,30,.22)`
- 阅读面浮层阴影柔和化：`0 1px 2px rgba(51,48,42,.08), 0 16px 40px rgba(51,48,42,.10)`
- 动效：沿用现有运动纪律（`--ease-out`/`--dur-*`/reduced-motion 归零块），本规范不新增动效

## 五、页面词汇表（状态即设计）

### 5.1 课程库书架（library.html v2 为准）
- **今日横条**：继续读卡（迷你书封 42×58 竖排书名 + 本周连击 7 点阵）+ 复习卡（mono 大数字到期数 + 连击点阵）
- **书卡**：立体封面 124×168（渐变布面 + 衬线书名 + `AI CLASSROOM · VOL.n` 书脊标 + 左折痕高光，hover 透视转 -5°）+ 右信息区（标题/一句话副题/状态 chips 带圆点/分篇分段进度条 + mono 计数）+ 底行（当前课 + 幽灵按钮）
- 分篇进度：段数=大纲 part 数；段内填充=该篇已学/篇内课数；part 数据缺失时退化为单条整卡进度
- 封面渐变色：沿用现有「哈希恒色」机制生成两档渐变（亮→深），不再用单色书脊

### 5.2 阅读器三栏（reader.html + classroom-panels.html 为准）
- 顶栏：纸底 blur + 底部纸纹线；进度条 2px 赭石贴顶
- 目录（160–400px 可拖）：当前节左赭石游标 + 卡片浮起 + 节内百分比；已读 ✓；未读降透明 0.62 不上锁；节下检查点圆点串（✓/○）+ 复习预告；底部打卡邀请横幅（warn 纸黄，仅「读到末尾且检查点未满」出现，按钮直达未过复述卡）
- 正文：纸卡居中 max 44rem；坑 callout（warn 三色 + 左粗边）；`源[N]` mono 赭石上标；插图 figure 纸卡；复述检查点卡 = 赭石虚线框 + 徽章 + 双按钮
- 答疑（260–560px 可拖）：纸底淡卡区；用户气泡 accent-soft 圆角 13（右下角 5°）；AI 气泡纸卡（左下 5°）；种子问题带来源标「◈ 来自检查点 n」可关闭；思考过程默认折叠可展开；课件节引用虚线下划 + `源[N]` mono 双引用；↳ 工具在飞行；流式光标闪烁 + ■ 停止；划词提示条常驻输入区上方
- 检查点弹层/闪卡/证据面板：换纸感 token，布局与交互一律不动

### 5.3 生成中心 + 观测
- 沿用 library.html 的卡片/阴影/chip 语言；现有 JobFeed 单行状态条、动效、轮询逻辑零改动，只换肤

## 六、任务拆解与验收

| 任务 | 范围 | 文件面 |
|---|---|---|
| T1 | 两区 token 落地 + ThemeSwitcher 退役 | `index.css`、`components/ThemeSwitcher.tsx` 删除、`app/Shell.tsx`/`features/reader/ReaderPage.tsx` 去引用 |
| T2 | Shell/导航/全局 chrome 工具面化 | `app/Shell.tsx`、全局 base 层 |
| T3 | 阅读面纸感 | `features/reader/*`、`features/chat/*`、`utils/linkify` 无关不动 |
| T4 | 书架书卡精修 | `features/library/LibraryPage.tsx`、`BookPage.tsx` |
| T5 | 生成中心 + 观测收尾 | `features/studio/*`、`features/eval/*` |

**全局验收（每任务必过）**：`pnpm -C apps/web lint` 零错、`tsc` 零错、build 通过；agent-browser 截图核对设计稿还原度（375/768/1280 三档无横向溢出）。
**行为零改动红线**：SSE/轮询/深链/滚动 spy/断点 localStorage 键（`reader-panels`、阅读断点、批改草稿）/拖拽栏宽/`?section=N`/复习深链/划词提问/mermaid 降级，语义一律不动；`apps/api`、`*.gen.ts`、`utils/linkify*`、`lib/learningPath.ts` 逻辑不碰；不新增依赖。
**公开仓库红线**：不提交 secrets；提交信息 Conventional Commits。
