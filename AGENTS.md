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
- ✅ **P1.5 全部完成(2026-08-21)→ 已封版**:A1~A6 + B0~B2 全过,明细见上一轮提交;收尾亦清(gen-types/A4多页/自评展示/traces 移出 git)
- ▶️ **当前阶段:P2 备课管线**(见 `docs/P2执行计划.md`,2026-08-24 对齐定稿:CLI 先行/不做 SVG/按页追加/MAX_TURNS=15)
  - ✅ **M1 校验器升级**:`app/services/csl_validator.py` 进程内校验(error/warn 分级,「第X页缺Y」可执行反馈,讲到什么亮什么机械规则),CLI 薄壳化;mypy strict 零错,harness-01 回归通过(`5f324e4`)
  - ✅ **M2a 找资料 agent**(`369a536`):双源框架(权威地图+用户待探合流)+带来源原料(source_id 硬闸,缺源打回);实测「Agent 解析层」:框架 8 足迹保序+2 地图补缺,原料 26 点/5 权威源。⚠️ 观测:阶段2 fetched=0(只吃搜索摘要没深读原文),M4 打磨时 prompt 要求至少 fetch 2 篇
  - ✅ **M2b 备课 agent**(`da67b3b`):四件工具精选(write_page=upsert-by-id 修错原语);天然收笔 harness 强制终验(客观终止);meta.sources/source_notes 确定性带入。实测「解析层」原料→9页/53句/4检查点课件,浏览器可上;产出**首份 agent 生成课件 parsing-layer**(软着陆一轮暴露工具缺陷→修→二轮通过,trace 全程可复盘)
  - ✅ **M3 TTS 编译**(`f9ac953`):tts_compile.py 确定性编译器(不进循环,图纸判据);备课收尾自动编译+自动发布前端(埋掉手动 sync 坑)
  - ✅ **M4 端到端**(`103419c`):pipeline.py 一条命令「主题→框架→[人审/auto]→原料→课件→音频→发布」;验收首跑真主题 **3.3 分钟**(红线 30)
  - ✅ **M5 课表入口**(`fe951c0`+`09538d3`):按钮派后台子进程跑管线(executor/job_runner,状态回写 SQLite,前端三态+轮询);source_notes 确定性覆盖保关联。实测:点「工具粒度」备课→课件出炉→自动进「在学的」
- 🏁 **P2 完成(2026-08-24)**:课表「在学的」4 门课(3 门 agent 生成:parsing-layer / function-calling-stability / tool-granularity),全链(调研→备课→音频→课表归位)自动。**待用户真实使用审校课件质量(人审闸②)**,反馈喂 prompt 打磨
- ▶️ **P3 进行中**:N1 三源蒸馏写回(`e5743c4`)、N2 学完判定+写回 UI(`5317a55`)已完成;**N3 端到端验收待用户真实学习触发(约定:2026-08-25 测试)**——学完一门课(播放到底+检查点全过)→邀请→预览→确认→vault 出笔记
- ✅ **P4 第一轮·课堂页 UI 重设计(2026-08-24,`0cd4e23`)**:借鉴 OpenMAIC(20.7k★ 同域)与 Slidev(48k★),参考库 clone 于 `~/CodeDevelopment/ui-refs`——页导航边栏(可拖宽/折叠)、o 总览/数字跳页/f 全屏、句级步进滑杆(seekSentence)、主题收纳 pill、fade 过场;唯一新依赖 lucide-react;全交互浏览器实测通过
- ✅ **P4 第二轮·信息架构五区制(2026-08-24,`0eecb31`)**:对标 LearnHouse/ClassroomIO×OpenMAIC——Shell 四区导航;学习台(继续学断点+推荐)/课程库+**详情页**(大纲+来源可点)/生成中心(我想学+笔记备课+任务状态)/课堂/观测;CatalogPage 拆除分流;共享 useCatalog+Lane
- ⏭ P4 第三轮候选:①观测拆 tab(agent 质量/学习进度);②生成中心·框架审阅 UI(双源框架→挑子题,现仅 CLI);③课程库按主题分组
- ✅ **插队任务·学习顺序+复习闭环(2026-11-02)**:用户提出「课表无前后顺序、学完不知怎么复习」,拍板两步走。竞品拆解先行(`docs/参考-同类项目拆解-2026-11.md`,8 项目代码级),采纳 DeepTutor/Study-Mate 裁剪版:
  - ①学习顺序:CSL `meta.depends_on`(id+reason,**人工标注不自动生成**;6 门课已标,harness-01 为根)→ 课程库卡片「⛓ 先修」+详情页「建议先学」+学习台「下一步学」(前置课 ready 才推荐;**只展示不锁进入**);校验器查自依赖/重复/缺 reason/指向不存在课件。**追加(同日):课程库顶部「学习路线·从这里开始」步骤条 + 卡片「路线第 N 步」+ 详情页「路线第 N/M 步·上一课/下一课」**——用户反馈「散落标记仍不知从哪看起」,按 depends_on 拓扑排序(Kahn,同分保持课程库序,环/悬空垫底)直接给出 1→N 顺序;实现在 `src/lib/learningPath.ts`(纯函数+拉取,课程库/详情页共用)。注意:路线条所在 LibraryPage 等文件尚混有未提交的 shadcn 重构,已随后者入库(`44ae5ac`+`8bfe4be`),路线/复习功能在重构后浏览器复验正常
  - ②复习闭环:`services/mastery.py`——/grade 成功后累积掌握度(最近 5 次加权 pass=1/warn=0.5/fail=0,低置信封顶 1 次≤0.5、2 次≤0.8「一次蒙对不算过」)+ 间隔序列 [1,3,7,14,30,60] 天(pass 且≥0.9 进位,fail 回 0 档;至少 pass 过一次才进复习轮)→ 学习台「今日复习」卡片 → 课堂 `?page=N` 深链重测(等 reveal initialize 完成再 slide,否则崩)。存 classroom.db `checkpoint_mastery` 表
  - 实测:批改→落库(0.5 封顶)→回拨到期→复习卡→深链落第 4 页,全链浏览器过;ruff 零错,mypy 与存量基线一致(34 处历史漂移非本次)
  - ⚠️ 课件 JSON 有两份:`apps/api/courses/`(源,后端读)与 `apps/web/public/courses/`(发布副本,前端读)——手改 meta 要两边同步(备课管线的发布步骤会自动拷贝)
  - ✅ **追加(同日)·先修建议进备课管线(`b0730e0`)**:「内容→顺序」接通——备课 agent 自动产出 depends_on:①「学员已有课程速览」确定性注入 prompt(id|标题|大纲,≤40 门);②`init_course` 增 depends_on 参数,harness 即时校验(自依赖/悬空 id/缺 reason/超 2 门→整体打回重交,不建文件,与 write_page 同自纠风格);③`pipeline.py` 交互模式课件出炉后 `confirm_depends_on` 人审(回车照单/clear/覆盖 id),生成中心 auto 直接落盘,路线拓扑排序自动跟随。实测:错误回收笔记备课全链过,agent 主动给出 `harness-01` 先修+具体教学理由(「死代码搭梯子心智模型直接复用」)
  - ✅ **追加(同日)·离线 agent 循环超时 60→240s(`b0730e0`)**:prep/research 用 `client.with_options(timeout=240)` 放宽,chat 的 60s 交互护栏不动——实测备课首轮长规划输出 7.4k tokens 在中转 ~46 tok/s 下需 191s,60s 必掐死(三连超时定位:走代理/直连都超时,非网络问题而是输出量×速度)
  - ⏭ Phase 2 已对齐方向未做:未知领域「该学什么」路线规划——找资料 agent 权威地图升级出课程级拆分(3~6 门+先修链),沉淀 vault「领域路线」笔记+候选池,挑一门钻取成课并自动链回兄弟课(动 research.py,先对齐再写)
- ✅ **P5 收口(2026-11-02,见 `docs/P5执行计划.md`)**:备课管线工程化——T0(在途 depends_on 由并行会话 `b0730e0` 提交,本轮单测复核)/T1(调研缓存复用 `5999590`)完成;同日用户拍板课件书页化,T2/T5/T6/T7 并入 P6,P5 剩余 T3(成本预估)/T4(log.md)模型无关可穿插
- ▶️ **P6 进行中:课件书页化迁移(2026-11-02 拍板,见 `docs/P6执行计划.md`)**:用户决定**放弃幻灯片形态**,CSL v1(页/句)→v2(节/块)真迁移为 DeepTutor 式滚动书页,文字+mermaid 插图,TTS 先砍留位(provider 保留不编译),检查点/复习/答疑保留(键语义页→节),reveal 路径退役:
  - 已拍板:真迁移(2~3 周)/TTS 砍留位/mermaid 并入 v2/不留双视图;v2 schema 草案在 P6 计划第二节
  - M0 拆两半:schema 对齐已过(用户审 P6 计划第二节后拍板「开始吧」);**prep 循环改造设计对齐保留至 M3 动刀前**(学习区闸)
  - ✅ **M1 完成(2026-11-02,`0b26587`)**:v2 节/块模型(7 种块)+双版本校验器+`scripts/migrate_csl_v2.py`;存量 7 门试运行 7/7 过(staging,原件未动,真正 --apply 随 M2);「≥3 测验」降为写作指引 warning(存量 function-calling-stability 仅 2 检查点属合法);节 id 沿用旧页 id→复习历史零映射;mastery/catalog/tts_compile 版本容忍,旧复习卡回归命中
  - ✅ **M2 核心完成(2026-11-02,`6c70d19`)**:书页阅读器 `/read/:id`——TOC+滚动 spy+断点(滚动位置 localStorage)+深链 `?section=N`+学完打卡;七种块渲染,mermaid 动态加载+失败降级代码块(含 body 错误元素摘除),quiz 内嵌复述卡复用 /grade(grader 增 v2 按节/块 id 定位),闪卡翻面;CheckpointOverlay 增 onClose;ChatPanel 进度依赖收窄 ProgressLike 双适配;v1 访问 /read 自动回退 /c。全块型预览件+真实迁移课浏览器实测全过;新依赖 mermaid(动态分包)。**预览:http://localhost:5273/read/_v2-preview**
  - ✅ **M2 完成(2026-11-02,`6c70d19`+`d38dd08`+`8ec6af8`)**:①核心:书页阅读器 `/read/:id`(TOC/滚动 spy/断点/深链 ?section=N/学完打卡;七种块渲染,mermaid 动态加载+失败降级并摘 body 错误元素;quiz 内嵌复述卡;闪卡翻面)②排版:prose 插件+CLREQ 微排版(行高 1.9/两端对齐/text-autospace)+霞鹜文楷正文字体(--font-reading);typo.css/heti 采纳规范不引库 ③flip:7 门课 v1→v2 原地迁移(v1 备份 data/v1_backup)、入口全切 /read、player 七文件+reveal 依赖+deck CSS 退役、掌握度旧行归并 -cp 键。E2E:复习卡深链→复述→LLM 批改通过→0.8 落库排期,全链截图过
  - ✅ **M3 完成(2026-11-02,`387a4e8`)**:备课 agent 书页化——submit_plan 规划外显(harness 校验:3~9 节/材料组 covers 显式覆盖/quiz≥3 硬闸;交互人审=回车照单或文字意见喂回重排一次;两次不过→静态模板兜底永不空转)+write_section(单节即时校验/upsert-by-id/写前双闸)+教材作者 prompt(书面 prose 禁课堂腔,七块型纪律,检查点 pass_rule 可判)+init_course 出 v2 骨架;validator v1 改退役指路;pipeline 删 TTS 步;trace_prep pages→sections。E2E 真跑:规划 6 节/4 检查点→逐节写→终验过;**首产书页原生课 context-compression-memory**(书面腔+源引用+3 mermaid+4 闪卡+主动建议先修),已发布可读
  - ✅ **M4 完成(2026-11-02,`bdd3ca8`)**:闪卡进复习队列——POST /flash/report(记得=pass/忘了=fail)复用检查点掌握度与间隔排期(忘了回 0 档明早再来,天然 Leitner);闪卡块 id 渲染期合成 `<节id>-fc<序>` 与 CourseV2.flash_lookup 同约定;due_reviews 双 lookup,到期卡带「闪卡 ·」前缀;阅读器翻卡后自评钮。单测:自评落库→进轮→回拨到期→队列出卡指向正确节
  - ⚠️ **M5 组合证据通过,单命令实测待复验**:T1(--reuse 零联网)+M3(备课真跑出 v2 课)+浏览器全链(读/批改/闪卡/队列)各环节均已实测;唯「一条命令新主题 30 分钟」的组合跑在中转拥堵夜反复超时(50 分钟未过规划期,SDK 240s 超时+内部重试静默烧时),已终止。缓存已就位(data/research/Agent上下文工程.*),真实使用时生成中心点按钮即复验——若再卡,优先查中转吞吐而非代码
- 🏁 **P6 实质收口(2026-11-02)**:书页形态全链落地——7 门课 v2、阅读器、备课直出 v2、闪卡复习闭环。遗留:①`p3-car` 的 mermaid 占位待人工补图(harness-01 汽车类比那张);②迁移课口语腔待人工润色;③单命令新主题实测复验(见 M5)
  - 差异化记账:转向后与 DeepTutor/Bloom 形态更近,差异化重心移到「生成管线有据硬闸+先修路线+复习闭环」轻量组合,竞品对照需重新校准
- ✅ **P4 第四轮·全站 UI 重设计:shadcn/ui 落地+三主题视觉升级(2026-11-02,`44ae5ac`+`8bfe4be`)**:技术栈表里的 shadcn/ui 名实相符(此前零组件层,25 个文件全手拼类)。方向经确认:shadcn(补 P1 §0 既定欠账,Mantine/HeroUI 运行时主题体系与 reveal/三主题不合)+视觉升级+全页面范围:
  - token:`@theme inline` 把三主题裸变量映射为 shadcn 语义色(壳层从 `bg-(--accent)` 迁往 `bg-primary` 等);新增 success/warning/danger/overlay 语义色;radius/字体 token;deck 排版类(`.deck-h1/.eyebrow/.muted` 三色工具)保留给 pages.tsx 课件专用,零改动(视觉≈samples 定稿)
  - 组件层:`ui/` 11 个基础组件(Button/Input/Textarea/Card/Badge 状态色/Dialog/DropdownMenu/Tooltip/Slider/Skeleton/Kbd)+共享业务组件 SectionHeader(收敛三种区块标题)/PageState/KindIcon(两份 KIND_ICON emoji 表归一为 lucide)/ThemeSwitcher(radix 重写,Shell 与课堂共用)
  - 字体真加载:@fontsource-variable 自托管 Noto Sans SC+JetBrains Mono(此前只声明未加载)
  - 体系化:遮罩统一 `--overlay`(字幕/检查点/Dialog/总览,替代写死 bg-black/70)、z-index 约定(nav=30/subtitle=40/dialog=50/tooltip=60)、focus-visible 全局 ring、emoji→lucide
  - 顺手修:ControlsBar 禁用态写成裸 JSX 属性的真 bug、播放钮补 aria-label、删 App.css 死代码
  - 验证:oxlint+tsc build 零错(6 个 warning 均既有模式/shadcn 标准导出);浏览器实测五页×主题切换持久化、播放/句级滑杆/重讲/o 总览/检查点批改弹层全过;与同日插队任务(学习顺序+复习闭环)同工作区并行,其页面层叠于本重构之上随 `8bfe4be` 一并入库,合并后路线条/今日复习复验正常
- ✅ 收尾已清(2026-08-24):gen-types 管线接上(catalog `59f15bc` + sessions `89b8ac1`;csl.ts 经决策保持手写——稳定的作者态契约,理由注记在文件头)、A4 多页可点(`5349427`)、B2 显示自评瞎编率(`6ecd5be`)、traces/ 移出 git(`05a0c2d`)。**P1/P1.5 收口完成**
- ⚠️ 长期记账(不阻塞 P2):①A4/ChatPanel 的 typescript-reviewer 屡被中转挡,恢复后补(现以 §3.1 自查+浏览器实测代替);②A6 局限:伪造「课件第N页」假引用会绕过自评 → `self_eval_fabricated` 是下限;③dev 服务器(API :8100 / web :5273,原 5173 与他项目冲突已改)会话结束需重启

---

## 常用命令（代码初始化后生效）

```bash
./start.sh          # 一键起前后端(旧进程自动先杀再重启;./start.sh api|web 单独重启)
cd apps/api && uv run ruff check app && cd ../web && pnpm run lint   # lint
pnpm -C apps/web gen-types   # OpenAPI → TS(需 API 已启动)
```

## AI 工具差异说明

- **Claude Code**：详见 `CLAUDE.md`（子 Agent 调用约定）
- 其他工具：遵守本文件；审查用 §3.1 清单代替
