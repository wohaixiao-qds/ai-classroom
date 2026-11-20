# AGENTS.md · AI 课堂项目工作规范

> 本文件是本仓库 AI 辅助开发的**唯一事实源**，按 harness 三层范式组织：Scaffolding（静态约束）/ Runtime（工作纪律）/ Eval（验证）。任何 AI 工具（Claude Code、Cursor、Copilot、Codex、Windsurf 等）在本仓库工作前必须先读本文件。

## 项目是什么

个人本地部署的 AI 老师课堂：FastAPI(Python) 后端 + React(TS) 书页阅读器，主题调研→领域大纲→逐课生成 CSL v2(节/块)→答疑/复述/间隔复习→预览确认后沉淀笔记。v1 幻灯片播放器已退役，TTS provider 留存但 v2 不编译音频。主线服务作者本人学习，未来演化成对外 AI 课堂。

---

# 一、Scaffolding —— 开工前必读的静态约束

## 1.1 文档索引（本文件的展开）

- `docs/设计方案-v1.md` —— 产品设计总纲（四 Agent 架构、场景、路线）
- `docs/P1执行计划.md` —— P1 阶段任务 T1~T6 及验收标准（已完成）
- `docs/P1.5执行计划.md` —— 历史阶段：答疑 agent 打磨(A1~A6) + AI 教室骨架(B0~B2)
- `docs/项目结构与开发规范.md` —— 目录结构、分层、API/工具链/Git 规范
- `docs/agent设计.md` —— 五维 × 每个 agent 的设计图纸（P2 备课施工依据）
- `docs/agent设计-现状梳理-2026-11.md` —— 当前 Agent 实现快照；阶段计划中的播放器与早期类型目录不再作为现状

## 1.2 边界铁律（违反=返工）

1. `apps/api` 与 `apps/web` **互不 import**；通过 HTTP(SSE) 与发布的静态 CSL JSON 连接，分别使用 `apps/web/src/types/api.gen.ts` 与 `csl.gen.ts` 生成契约
2. **跨语言不手写共享类型**：HTTP 从 FastAPI OpenAPI 生成；静态 CSL 从后端 Pydantic schema 包装为内存 OpenAPI，复用 `openapi-typescript` 生成。`csl.ts` 仅作类型出口和前端视图函数，`pnpm -C apps/web check-csl-types` 检查漂移
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
| 前端 | React · Vite · TypeScript · Tailwind v4 · shadcn/ui · react-markdown · mermaid；书页阅读器与自建 SSE 对话 UI |
| 契约 | OpenAPI 生成 HTTP 与静态 CSL 的 TS 类型；SSE 传输事件 |
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

1. 只做当前用户明确授权的任务及其前置；阶段任务按对应执行计划，P1/P1.5 为已封版历史，不限制后续已授权阶段
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

- 当前主线：**书页课堂已落地，进行 Agent 架构审查收口**。以下为按时间保留的阶段历史，后续条目中的完成记录优先于早期“进行中”标记。
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
- 🏁 **P5 全部收口(2026-11-02,`8380d03`+样课先行)**:T0/T1 完成;T3 成本预估(services/estimate.py:traces 最近 5 次 ok 均值,子题选定即打印「调研≈N分/轮·备课≈N分/轮·合计(红线30)」,无历史给默认档;注意 read_traces 最新在前,[:5] 才是最新)+T4 课件操作日志(prep._op_log → data/research/{id}.log.md,append-only 一行一操作 init/write/replace/validate/deliver);**样课先行**(claudemy 同款):生成中心一句话开课 = research_framework 出领域大纲 → 自动备大纲第一门样课 → 其余课在大纲逐课点单
- ▶️ **P6 进行中:课件书页化迁移(2026-11-02 拍板,见 `docs/P6执行计划.md`)**:用户决定**放弃幻灯片形态**,CSL v1(页/句)→v2(节/块)真迁移为 DeepTutor 式滚动书页,文字+mermaid 插图,TTS 先砍留位(provider 保留不编译),检查点/复习/答疑保留(键语义页→节),reveal 路径退役:
  - 已拍板:真迁移(2~3 周)/TTS 砍留位/mermaid 并入 v2/不留双视图;v2 schema 草案在 P6 计划第二节
  - M0 拆两半:schema 对齐已过(用户审 P6 计划第二节后拍板「开始吧」);**prep 循环改造设计对齐保留至 M3 动刀前**(学习区闸)
  - ✅ **M1 完成(2026-11-02,`0b26587`)**:v2 节/块模型(7 种块)+双版本校验器+`scripts/migrate_csl_v2.py`;存量 7 门试运行 7/7 过(staging,原件未动,真正 --apply 随 M2);「≥3 测验」降为写作指引 warning(存量 function-calling-stability 仅 2 检查点属合法);节 id 沿用旧页 id→复习历史零映射;mastery/catalog/tts_compile 版本容忍,旧复习卡回归命中
  - ✅ **M2 核心完成(2026-11-02,`6c70d19`)**:书页阅读器 `/read/:id`——TOC+滚动 spy+断点(滚动位置 localStorage)+深链 `?section=N`+学完打卡;七种块渲染,mermaid 动态加载+失败降级代码块(含 body 错误元素摘除),quiz 内嵌复述卡复用 /grade(grader 增 v2 按节/块 id 定位),闪卡翻面;CheckpointOverlay 增 onClose;ChatPanel 进度依赖收窄 ProgressLike 双适配;v1 访问 /read 自动回退 /c。全块型预览件+真实迁移课浏览器实测全过;新依赖 mermaid(动态分包)。**预览:http://localhost:5273/read/_v2-preview**
  - ✅ **M2 完成(2026-11-02,`6c70d19`+`d38dd08`+`8ec6af8`)**:①核心:书页阅读器 `/read/:id`(TOC/滚动 spy/断点/深链 ?section=N/学完打卡;七种块渲染,mermaid 动态加载+失败降级并摘 body 错误元素;quiz 内嵌复述卡;闪卡翻面)②排版:prose 插件+CLREQ 微排版(行高 1.9/两端对齐/text-autospace)+霞鹜文楷正文字体(--font-reading);typo.css/heti 采纳规范不引库 ③flip:7 门课 v1→v2 原地迁移(v1 备份 data/v1_backup)、入口全切 /read、player 七文件+reveal 依赖+deck CSS 退役、掌握度旧行归并 -cp 键。E2E:复习卡深链→复述→LLM 批改通过→0.8 落库排期,全链截图过
  - ✅ **M3 完成(2026-11-02,`387a4e8`)**:备课 agent 书页化——submit_plan 规划外显(harness 校验:3~9 节/材料组 covers 显式覆盖/quiz≥3 硬闸;交互人审=回车照单或文字意见喂回重排一次;两次不过→静态模板兜底永不空转)+write_section(单节即时校验/upsert-by-id/写前双闸)+教材作者 prompt(书面 prose 禁课堂腔,七块型纪律,检查点 pass_rule 可判)+init_course 出 v2 骨架;validator v1 改退役指路;pipeline 删 TTS 步;trace_prep pages→sections。E2E 真跑:规划 6 节/4 检查点→逐节写→终验过;**首产书页原生课 context-compression-memory**(书面腔+源引用+3 mermaid+4 闪卡+主动建议先修),已发布可读
  - ✅ **M4 完成(2026-11-02,`bdd3ca8`)**:闪卡进复习队列——POST /flash/report(记得=pass/忘了=fail)复用检查点掌握度与间隔排期(忘了回 0 档明早再来,天然 Leitner);闪卡块 id 渲染期合成 `<节id>-fc<序>` 与 CourseV2.flash_lookup 同约定;due_reviews 双 lookup,到期卡带「闪卡 ·」前缀;阅读器翻卡后自评钮。单测:自评落库→进轮→回拨到期→队列出卡指向正确节
  - ✅ **M5 钉死(2026-11-03)**:「一条命令新主题 → 大纲 → 样课」真跑通过——`pipeline "RAG 检索增强" --auto` **14.6 分钟**(红线 30)交付 5 节/31 块/5 检查点;T3 预估线在真实运行点亮(预估 20.1 vs 实际 14.6,<2× 达标);T4 日志逐行可读;RAG 大纲 8 门自动入书架成第 5 本;样课先行同步上线(生成中心开课=出大纲+自动备第一门样课)
- 🏁 **P6 实质收口(2026-11-02)**:书页形态全链落地——7 门课 v2、阅读器、备课直出 v2、闪卡复习闭环。遗留:①`p3-car` 的 mermaid 占位待人工补图(harness-01 汽车类比那张);②迁移课口语腔待人工润色;③单命令新主题实测复验(见 M5)
- ▶️ **P7 进行中:领域大纲一等公民(2026-11-02 立项,见 `docs/P7执行计划.md`)**:用户定调产品主线——「我说我要学 X→调研 GitHub→出课程完整大纲→我按大纲点单备课→出关联小课程」;框架(subtopics)升级为大纲(courses 带 goal/prereqs DAG),并把大纲产品化(生成中心审阅+逐课备课+课程库领域视图):
  - ✅ **M1 完成(2026-11-02)**:research 框架 prompt 升级为「课程大纲设计师」(3~8 门,goal 可验证禁了解/熟悉,prereqs 成 DAG,入口课无前置);validate_framework 重写(Kahn 环检测/悬空引用/自依赖/数量闸);旧 subtopics 缓存按需转 courses 不报废;pipeline/CLI 切 courses 字段。真跑「Agent Harness」3 分钟出 8 门单链大纲(goal 全部可验证,源自 vault 足迹),缓存已落 data/research/Agent-Harness.framework.json
  - ✅ **M2 完成(2026-11-02)**:领域大纲可见可审可点单——①路由 `routes/outline.py`(列表/详情含出课判定与备课状态/PUT 调整过校验器落盘/POST 点单);②job 新 kind `outline_prep`(target="主题::课名":缓存优先原料调研→备课承接前置课→**大纲钦定先修链覆盖模型建议**(按标题匹配已出课,前置未出课先欠着)→发布);③生成中心 OutlinePanel:大纲 pill→课程表(目标/先修链/已出课✓·备课中·失败可重试徽章)+备课按钮+↑↓✕调序保存(8s 轮询状态自动跟走);浏览器实测:大纲展示/PUT 往返/点单→「备课中」徽章实时点亮
  - ✅ **M3 完成(2026-11-02)**:书籍式领域目录——大纲 schema 增 part 字段(prompt 要求归成 2~4 篇,validator 校验 part 非空串),Agent Harness 现有大纲手工归 3 篇(基座/护栏/评估迭代);生成中心按篇分组;课程库新增 OutlineToc 书籍目录卡(篇→课+goal+✓已学/▶当前+「已学 N/M」计数,插在学习路线条下方)
  - ✅ **追加(同日)·大纲收编存量课**:用户指出「大纲只覆盖规划课,整体知识点都该有大纲」——①research 框架 prompt 注入全部已出课程速览+收编规则(对应内容优先充当大纲课程并填 course_ref=课件id);②修 flip 遗留:_course_brief 还在读 v1 pages(对 v2 课件已静默失效,先修建议半瞎),改读 sections 兼容双版本;③出课匹配升级三级:course_ref(调研钦定)>meta.outline_course_id(outline_prep 出课写回)>课名;④真跑验收:Agent Harness 大纲重调研收编 harness-01/parsing-layer-v2,点单出的 state-side-channel 自动挂回大纲,3/8 已出课解析全对
  - ✅ **追加(同日)·大纲立场反转+知识版图归位**:用户纠正「大纲应该面向零基础学习者设计从开头到结尾的完整路线,而不是按已有知识点编写;使用者对知识点没有概念」——①框架 prompt 重写:删收编规则/已出课注入/vault 足迹,立场改为「权威地图为纲的零基础完整路线」,part=学习阶段(起步→核心机制→工程化→实战),顺序即学习顺序;②真跑验收:Agent Harness 新大纲 8 门四阶段,从「画出模型 vs harness 边界图」到「组装微型编码 harness」,完全不看已有知识;③知识版图归位:meta.topic 曾有 6 种写法+5 门 None(「harness 有好几个」的根源),一次性回填到 vault 层级(Agent/harness/{核心概念,Runtime,Scaffolding}+MCP),outline_prep/pipeline 出课时经 find_todo_area 归位
  - ✅ **追加(同日)·旧课归位+多对一挂接(`357469d`+后续)**:用户选「旧课归位到大纲」——①一次 LLM 归属匹配(只配合起来实质覆盖大纲课核心的,一对多:一门大纲课可收多门旧课,一门旧课只归一门;拿不准不归),写 course_refs 列表落盘;②路由/目录/生成中心全链消费 refs:课程库目录行下渲染旧课 chips(可点读),「已挂 N 门」计数;③真跑:工具层←[Function calling+MCP+解析层] 三课合归,3/8 有内容。已知取舍:归位后的行不再出「备课」钮(要整合版需手动删 refs 再点单);course_ref 单值字段保留做兼容
  - ✅ **追加(2026-11-03)·去「学习路线」+生成中心改造(`04c1098`)**:用户拍板「学习路线条去掉(大纲书本身就是路线),课程库只展示大纲,存量课全归位」——①学习台:书架进度视图(每本书一行:已学 N/M+当前课▶+继续读)取代学习路线条,下一步学=第一本没读完的书的书内游标;②详情页:上一课/下一课改书内相邻(直达阅读器);③生成中心:任务动态并入大纲点单(GET /outline-jobs),job 尾部出课自动归位(attribute_all,失败不影响交付);④退役 suggestOrder 全局拓扑排序;⑤修同名课覆盖 bug(课名→id 索引改列表保留同名课;render 端 file→course_file_id 修正=书架误显示全部学完的根因)。浏览器四页实测全过
  - 🏁 **P7 M1~M3 收口**:「我要学 X→调研出零基础完整学习路线(带篇章与先修链)→生成中心审阅调整→逐课点单备课/旧课归位→自动挂学习路线与知识版图→课程库书式目录看进度」全链落地。遗留:大纲课改 id 断链(手动调);出课后自动归位若误归,生成中心删 refs 重归
- ✅ **追加(同日)·修 v2 答疑底料断裂(`d289f6a`,联动功能的拦截弹)+批改↔答疑联动**:用户反馈「复述点点击后问题发到了对话框但老师没启动」→根因=**tutor.course_text_of 仍读 v1 pages,P6 flip 后答疑对所有 v2 课件都是坏的**(KeyError→500→前端静默空泡;与 grader/mastery 同类的迁移漏网——**修迁移时 grep 老字段名清点消费方**,course_text_of 当时漏网)。修复:v2 读 sections+各块全要素,v1 兼容;ChatPanel 补 resp.ok 检查(HTTP 错误亮出不再静默)。联动:ChatRequest 增 checkpoint 上下文,tutor 注入引导式指令,复述卡「没懂,问 AI 老师」双态按钮(提交前/后),真跑:批改存疑→老师准确识别未提交并顺势引导填空
- ✅ **追加(2026-11-03)·检查点通过态展示(`f22c008`)**:用户要求「答过并通过后展示我的回答+标准版答案」——overlay onPass 上抛整份结果(score/comment/precise/answer),QuizCard 通过态渲染得分+我的回答+标准表述同屏;打卡反馈显示检查点通过 x/y 与沉淀解锁条件。中转持续抖动(间歇 502,批改三重试仍偶发全挂),通过态的最终截图验证待中转稳定
- ✅ **追加(2026-11-03)·沉淀弹窗生命周期改造(`b0120de`)**:用户需求「蒸馏中关弹窗能再打开;生成后可选重新生成/再次查看,落盘前一直可访问」——显式 draftDialogOpen 取代派生;closeDraft 只关弹层(SSE 蒸馏继续跑,重开接进度/草稿);新增 cancelDraftGen(中止流)与 regenerateDraft(清草稿重跑);busy 视图补取消生成钮,预览页脚补 ↺ 重新生成。运营注意:dev server 运行中 pnpm 动依赖会静默杀死 vite(全站 Failed to fetch,页面照常渲染的假象),动依赖后必须 ./start.sh web
- ✅ **追加(2026-11-04)·修「确认写回没反应」(用户报,根因=SSE 重构孤儿化缓存)**:用户在《编排循环》写回点确认毫无反馈——根因链:①draft-stream SSE 重构(`87ce13f`)**漏了把 done 草稿回填 _DRAFT_CACHE**,而 apply 缓存未命中时静默 build_draft 重蒸馏 2~3 分钟→期间前端零 busy 态→「没反应」假死;②且落盘的是用户没预览过的新草稿,违反「确认的必须是预览过的那份」不变量(实测:确认两次=正文+一段未预览增补,连诊断探针都被静默追加污染,已全部裁净、增补给用户留档 /tmp)。三修:①draft_stream done 事件回填缓存;②note_apply 缓存未命中改 **409 拒绝**(不再静默重生成,文案引导重新预览);③confirmWrite 补 applying busy 态(按钮「写入中…」+三钮禁用)。连带发现:**5.3 蒸馏 16384 预算被思考全烧光零文本**(stop=max_tokens,blocks=['thinking']),note_writer 三调用点提 **32768**/超时 600s(官方上限 128K、示例 65536)。E2E:SSE 蒸馏 76s→apply **0.02s** 200(修复前 2~3 分钟静默)→重复点击 409 秒拒。教训归档:①uvicorn reload 卡「Waiting for connections」kill -9 救(实锤第四坑);**对修改中的端点做探测前先确认重载完成——否则测的是旧代码还污染数据**;②重载父进程被杀后 spawn worker 成孤儿,./start.sh api 干净重启
- ✅ **追加(2026-11-03)·批改百分制(`grader` 重写,用户规格)**:「按输入打分,<70 要求重新复述或问 AI 老师后再复述就过;≥70 保留答案+精准版并判过」——①prompt 评分标尺(85+全对/70-84 核心说清/40-69 漏关键/0-39 说反),输出 score;②服务端 score≥70 判 pass,<70 判 fail;tutored(问过老师)保底 70;③trace/note_writer 落 score+precise(答案与精准版都进笔记);④overlay 得分徽章+非 pass 双钮(问老师/重新复述);⑤双真跑:弱答案 30 分 fail(点评准确点名漏了生成端与双记忆)→tutored 重试 70 分过。中转抖动致两次 502(重试机制吞掉一次)
- ✅ **追加(2026-11-03)·批改 502 真因修复:思考模型 max_tokens 预算(`grader`)**:排查批改间歇 502——直接探中转 5/5 全通(2~3s),排除中转;真因=GLM 思考模型的思考块**也吃 max_tokens 预算**,批改 1024 被思考烧光→零文本→JSON 解析失败→「返回格式异常」502,间歇性=思考长度随 prompt 浮动。修复:8192(与 prep/归位同档)+零文本时亮 stop_reason 与块类型。教学教训归档:bg-llm-job-ops 记忆
- ✅ **追加(2026-11-03)·手动取消+中断续上(`5a04e4d`,四类任务全支持)**:用户需求「所有 agent 任务可手动撤销并续上」——①Jobs 取消:executor PID 文件登记+cancel_job(SIGTERM 进程组)+POST /jobs/cancel+job_runner SIGTERM 钩子(清 0 节骨架+置 cancelled);②备课续写:RESUME_PROMPT+run_prep(resume_course_id)+outline_prep 重发自动判续/判重(同名课件在盘=续写);③答疑停止:AbortController+停止钮,run_tutor try/finally 断连落半截答案(孤儿轮治理);④批改草稿 localStorage 持久+GET /grade/last 回查(通过态跨刷新);⑤生成中心 busy 行取消钮。实测:点单→取消→进程消失+状态 cancelled 全链过;备课续写语法/结构验证,长任务 E2E 留真实使用复验
- ✅ **追加(2026-11-03)·批改 502 重试(grader 三连发)**:用户报批改 502——日志显示同端点 502/200 交替(中转间歇抽风),而批改 LLM 调用只试一次;grader 加 3 次重试(1.5s 递增退避),真跑 200 通过(17.5s 含内部重试)。注意:链路测试把用户 p2-formula-cp 复述卡代答了两遍(判通过),该卡下次复习被排后——如实告知。仍 502 时=中转持续拥堵,重试/稍后再试即可
- ✅ **追加(2026-11-03)·打卡无反应三连修(P6 迁移漏网清剿)**:用户报「学完打卡没反应」——①`progress.completion` 仍用 v1 模型解析(v2 崩溃静默返回未就绪,**打卡其实一直有记录**,只是判定永远读不到)+检查点只认 v1;改 raw json 双版本(quiz 块=检查点);②`note_writer._render_course` 同病(v2 笔记会渲染空内容);③阅读器打卡补反馈 UI(「✓已打卡·检查点 x/y」,未就绪说明差什么)。真跑:recognize 课 done=true/4 检查点/通过 0——反馈如实。**审计结论:v1 字段消费方已清零**(progress/note_writer/tutor/course_text_of/grader/mastery/catalog/tts_compile 全部双版本)
- ✅ **追加(同日)·批改↔答疑联动+答疑落笔记确认(`e8abbda`)**:用户需求「批改要和答疑联动(多轮解答),答疑过程落 Obsidian」——①发现答疑过程本就在 P3 蒸馏源(_render_dialogs),限额 6→10 会话/200→300 字;②联动:ChatRequest 增 checkpoint 上下文(问题/标准/学员回答/判定),run_tutor 注入首条 user(引导式解答不直接给答案),复述卡非 pass 态「没懂,问 AI 老师」→关 overlay→ChatPanel 种子自动发送(多轮追问)。真跑:批改存疑→问老师→准确解答参数/非参数记忆。事故复盘:三段式修补第一段失败退出,②③未应用但误以为已应用——「每段独立验证」再证必要
- ✅ **追加(同日)·课程库事故+学习框架可视化(`c145963`+`51339e0`)**:①M5 被杀运行留下 0 节骨架课(id 是英文 slug,按中文 grep 漏检),进 catalog「在学的」但发布副本缺失→课程库整页炸;处置=删半成品+fetchAllCourses 单门跳过(一门坏课不再拖垮整页)。②用户反馈「学习框架没搭起来/顺序展示不明显」:学习台顶部学习路线步骤条(✓已学/▶当前步,标题带「你在第 N/M 步」,仅靠 catalog 的 depends_on 免拉全量)+下一步学改路线游标卡(第一个未学完=当前步,带承接说明+开始学 CTA)+课程库路线条当前步高亮;顺手修 flip 遗留——继续学还读旧播放器 localStorage 键(阅读器从不写),断点续学实际已死,现阅读器存 {top,sec}、学习台显示「接着学·第 N 节」深链回读
  - 差异化记账:转向后与 DeepTutor/Bloom 形态更近,差异化重心移到「生成管线有据硬闸+先修路线+复习闭环」轻量组合,竞品对照需重新校准
- ✅ **P4 第四轮·全站 UI 重设计:shadcn/ui 落地+三主题视觉升级(2026-11-02,`44ae5ac`+`8bfe4be`)**:技术栈表里的 shadcn/ui 名实相符(此前零组件层,25 个文件全手拼类)。方向经确认:shadcn(补 P1 §0 既定欠账,Mantine/HeroUI 运行时主题体系与 reveal/三主题不合)+视觉升级+全页面范围:
  - token:`@theme inline` 把三主题裸变量映射为 shadcn 语义色(壳层从 `bg-(--accent)` 迁往 `bg-primary` 等);新增 success/warning/danger/overlay 语义色;radius/字体 token;deck 排版类(`.deck-h1/.eyebrow/.muted` 三色工具)保留给 pages.tsx 课件专用,零改动(视觉≈samples 定稿)
  - 组件层:`ui/` 11 个基础组件(Button/Input/Textarea/Card/Badge 状态色/Dialog/DropdownMenu/Tooltip/Slider/Skeleton/Kbd)+共享业务组件 SectionHeader(收敛三种区块标题)/PageState/KindIcon(两份 KIND_ICON emoji 表归一为 lucide)/ThemeSwitcher(radix 重写,Shell 与课堂共用)
  - 字体真加载:@fontsource-variable 自托管 Noto Sans SC+JetBrains Mono(此前只声明未加载)
  - 体系化:遮罩统一 `--overlay`(字幕/检查点/Dialog/总览,替代写死 bg-black/70)、z-index 约定(nav=30/subtitle=40/dialog=50/tooltip=60)、focus-visible 全局 ring、emoji→lucide
  - 顺手修:ControlsBar 禁用态写成裸 JSX 属性的真 bug、播放钮补 aria-label、删 App.css 死代码
  - 验证:oxlint+tsc build 零错(6 个 warning 均既有模式/shadcn 标准导出);浏览器实测五页×主题切换持久化、播放/句级滑杆/重讲/o 总览/检查点批改弹层全过;与同日插队任务(学习顺序+复习闭环)同工作区并行,其页面层叠于本重构之上随 `8bfe4be` 一并入库,合并后路线条/今日复习复验正常
- ✅ **P4 第五轮·全站动效体系:CSS 打底+motion 管 FLIP(2026-11-03,`804cbb8`+`37fce43`+`faa18fc`)**:用户看过 Collect UI/Prompt Motion 两个设计站后拍板「全站再借鉴+加动效」。引擎分工经确认:**混合**——CSS 体系打底(绝大多数场景)+`motion` 库只管 4 处 FLIP/Presence;范围=全量三批:
  - 地基:index.css 运动纪律注释(借 Prompt Motion direction 语法:springs 微过冲/只动 transform-opacity/Banned 清单)+`--ease-out`(继承 deck 旧曲线)/`--ease-spring` 双缓动+anim-rise/pop/drop/shimmer 工具类+`::view-transition` 路由过渡样式+**全局 prefers-reduced-motion 归零块**(P6 删 deck 时随 .step 丢失,重建);App 加 `MotionConfig reducedMotion="user"`;Shell NavLink 加 viewTransition(原生路由过渡,不支持的浏览器自动硬切);新依赖仅 `motion`
  - 断层修复:检查点弹层裸条件渲染零动画→AnimatePresence 进出场;闪卡文本瞬换→CSS 3D rotateY 翻面(隐藏面 aria-hidden);quiz 通过色 transition-colors+勾 anim-pop;EvalPage 两处折叠硬弹→新共享组件 Collapse(grid-rows 0fr→1fr);mermaid SVG 硬替换→anim-rise 淡入
  - 阅读器精修:TOC 高亮硬切→motion layoutId 滑动指示 pill;打卡邀请横幅 anim-drop 顶部落下;**刻意不做**正文滚动触发的逐块浮现(阅读面保持安静)
  - 数据动效:EvalPage Metric 纯数字 useCountUp 滚动(rAF,读系统减少动态);学习路线▶游标/OutlinePanel 大纲 chips 选中底色 layoutId 滑动;OutlinePanel 课程条目 motion layout,↑↓ 重排 FLIP 不再硬跳;OutlineToc 状态图标轮换 anim-pop;hover 补齐(想学的行/火花卡/下一步学卡/写回成功勾)
  - 验证:oxlint+tsc 零错(9 warning 均既有模式同类);浏览器实测路由过渡/TOC 滑动/闪卡翻面/弹层进出/折叠/C 主题观感,`set media reduced-motion` 模拟降级后功能全过
- ✅ **追加(同日)·备课可观测性+进行时动效(`bc4525b`+`ab55347`)**:用户要求「备课也带动效+把模型思考处理的消息亮出来」。发现处理消息早已完整落盘(executor 派的子进程 stdout→data/logs/*.log,含 submit_plan 规划/init_course 建骨架/write_section 逐节写/validate_csl 终验/FAILED 原因),缺的只是口子:
  - 后端:GET `/api/v1/jobs/log?kind&target&tail` 只读尾部(executor 抽 `log_path_for` 单一事实源防路径漂移;kind 枚举闸);**不碰 agent 代码**
  - 前端:新组件 JobFeed(2s 轮询+阶段标记着色+新行 anim-rise 浮入+自动滚底,active=false 停轮询留末屏)+anim-progress 不确定进度线(分钟级等待的活着信号);三面接入——生成中心「正在造」行内嵌 feed、大纲面板 busy 行 feed/failed 行直接亮失败原因、课程库目录 busy 行进度线;任务记录 failed 行也带日志尾部
  - 书架视图(并行 `04c1098` 去学习路线重构)动效重铺:每本书进度线(done/total width 过渡)+深链 viewTransition+下一步学卡浮起;原「路线游标」随步骤条功能退役自然消失
  - 验证:端到端真跑命中——恰逢并行会话派的「编排循环:harness 的心跳」备课运行中,页面实时看到逐节写入→终验✅→大纲挂接→发布→归位→DONE 全生命周期,任务完成卡片自动退场;ruff 零错,mypy 与存量基线一致(37 处历史漂移非本次),oxlint/build 零错
- ✅ **追加(同日)·大纲层「已出课件」标记(`4da4e0a`)**:用户要求「给个标记已经有课件的」。出课判定(course_refs∪course_ref∪outline_course_id 链∪课名兜底)从详情端点抽成 `_course_file_ids` 共用(列表/详情单源,顺带修 mypy 基线 1 处);`GET /outlines` 列表带 `prepared` 计数(索引扫描一次);生成中心大纲 chips 已出 N>0 时 success 色标注(如 Agent Harness(8) 已出 6),课程库目录卡头「已出 N · 已学 M / 总」——出了课≠学了,两口径分开。浏览器实测两处渲染 ✓
- ✅ **追加(同日)·挂接课手风琴(`94b3eb2`)**:用户拍板「课程库挂了课的用手风琴展示」。目录里挂多门旧课的行原本常驻平铺 chips(撑乱目录节奏),改为「已挂 N 门」展开钮(chevron 翻转+aria-expanded)+复用动效体系的 Collapse 缩进列表(左边线+FileText,点行去读,新行 viewTransition);单挂行保持直达;reduced-motion 自动降级
- ✅ **追加(同日)·修备课输出缓冲吞没+等待期样式(`e0a3651`)**:用户反馈「一直没有模型的思考输出」。根因=executor 派子进程没加 `-u`:stdout 对文件块缓冲,阶段 print 全憋到退出才落地(「必须 python -u」老坑,接 feed 时漏了)——executor 补 `-u`,新任务逐 print 实时落盘(已在跑的旧任务不回填);样式:anim-progress 提对比+线高 1,JobFeed 空态改 spinner+「模型思考中」+已等待秒数计时,min-h 撑盒/max-h-56 滚动
- ✅ **追加(同日)·滚动容器呼吸位(`eeb5236`)**:用户指出内容与滚动条间隔太挤。自定义细滚动条占 8px 布局宽,px-3 的容器只剩 4px 视觉间隙——统一右留白:JobFeed 日志框 pl-3 pr-5(长行贴滑轨重灾区)、答疑消息区 pl-4 pr-5、阅读器目录 pl-3 pr-4;经 getComputedStyle 实测生效(16/20px)
- ✅ **追加(同日)·模型调用观测层(`8e1b2e9`)**:用户追问「为什么一直就是一句话」——两阶段 print 之间的几分钟(research 多轮 tool-use 循环、单节 write)全程静默。在共享层 `app/core/llm.py` 包 messages.create(**不碰 app/agent/ 循环**):每次模型调用打「⋯ 模型调用 #N…」/「✓ #N 完成 · 耗时 · tokens」心跳行,python -u 实时进任务日志;stream(答疑)与其余属性透传,with_options 派生客户端同样带观测。前端:尾行 ⋯ 脉冲示意调用进行中,✓ 完成行微亮。**遗留(②闸)**:工具调用级语义发射(「↳ web_search(<词>)」在飞提示)需动 tools.py/循环,待人对齐再动
- ✅ **追加(同日)·工具在飞提示(`239929d`,②闸已对齐)**:用户拍板「动吧,想让用户看到 agent 到底在干什么」。按对齐方案落:tools.py 加 `emit_call`(纯观测,工具执行前打「↳ 工具名(参数摘要≤60字)」),三个执行点各插一行——tools.execute_tool(答疑/通用)、research._execute、prep dispatch(备课五件套),research/prep/tutor 三循环全覆盖;JobFeed lineTone 给 ↳ 在飞行亮白。顺带:观测客户端 Any 化后 4 处失效 type:ignore 摘除,mypy 基线 37→34。**新派的任务**即可见完整过程:思考中计时→模型心跳(⋯/✓)→工具在飞(↳)→阶段行(规划/建骨架/逐节/终验)→DONE
- ✅ **追加(同日)·单行状态条(`9bc82e9`)**:用户拍板「一行展示动态替换,和 AI 工作时一样」。JobFeed 从滚动日志列表改为单行状态条:盒内只显示**最新一行事件**(模型心跳/工具在飞/阶段完成),key 随内容变→淡入-rise 原地改写不堆历史;右侧已等待秒数;长行截断+悬停看全文;盒顶进度光条保留。真跑验证:护栏与沙箱流式推进,状态行 [init_course] 原地替换、秒数走字
- ✅ **追加(同日)·修任务动态陈旧(`534dc1d`)**:用户问「可观测为啥还没备课成功」——实际 12:25 已 done(课件 harness-observability-evals),跑了 ~51 分钟(中转拥堵夜已知特征,与 M5 那次 50 分钟级同因);看起来没成功的根因是**任务动态只在进页时拉一次**,跑完了页面还挂着旧的「正在造」。改 8s 轮询。另:outline-jobs 列表按尝试次数出行,「工具层 failed」是 11:06 那次失败记录,重跑已成功出课(harness-tool-layer 已在已出计数里)
- ✅ **追加(同日)·任务盒一体化(`6d710f7`)**:用户指出「loading 图标不用两个,过程直接在框里展示」。JobFeed 重构为单一表面:盒顶 anim-progress 光条+思考中计时+阶段行全部内聚,正在造行头 spinner 与独立进度线、大纲面板 busy 行独立进度线全删——全卡只剩盒内一个加载指示。真跑对比同屏验证:`-u` 修复后派的「护栏与沙箱」流式出行(复用大纲缓存…),修复前的「可观测与评测」诚实显示思考中+秒数
- ✅ **追加(同日)·修写回草稿 500(用户报 `SyntaxError: Unexpected token 'I'`,根因链三修)**:课程库写回草稿预览炸 JSON 解析——纯文本 500 被前端 `.json()` 硬解。三层:①根因=note_writer 蒸馏沿用 chat 60s 交互护栏,实测三源蒸馏 157~192s 必掐死(ReadTimeout→裸 500),放宽 240s(同 prep/research 惯用法,写回蒸馏当时漏网);②二程=思考模型把 8192 预算全烧光零文本(蒸馏整课比批改思考重,grader 档位不够),提 16384+零文本亮 stop_reason/blocks(同 grader 判别);③learning 路由补 /grade 同款异常→502 可读 JSON,前端 LibraryPage errText(非 JSON 响应体透原文,不再 SyntaxError)。真跑 recognize-harness-software-layer:草稿全文出炉(frontmatter+正文),不用再撞 500
- ✅ **追加(同日)·glm-5.3 备课管线对照实验(用户拍板「验证一下」)**:端点探测(glm-4.6/5.3/5.3-flash 全通;同 prompt 实测三者速度无差 ~35-40 tok/s;**5.3 思考不可关且 reasoning_effort/thinking.budget_tokens 在 anthropic 兼容端点全被忽略**)→ `.env` LLM_MODEL=glm-5.3 真跑 `pipeline "RAG 检索增强" --auto`:**17.8 分钟**(M5 同题 4.6 全新链 14.6 分钟,+22%,红线 30 内;其中两轮 8.2k 全思考零工具调用被重试,纯损耗 ~330s/16k out——prep 的 8192 对 5.3 贴天花板,若留需考虑提高)。质量同码同 prompt 对照:**行内引用 0→23 次,含具体数字块 1→5,调研层自发 fetch_page 12 篇**,时效细节显著更深(RAGFlow rc1-rc3 精确日期/GraphRAG 维护模式/LangChain rubric-checked grounding)。副作用:新课 rag-open-book-hallucination-staleness 与旧 M5 课 rag-open-book-exam 并存于书架(未互相挂接,留哪门待用户定);**.env 仍在 5.3,API 进程未重启仍是 4.6**——全站去留待拍板(答疑侧思考不可关→首字延迟是主要顾虑)
- ✅ **追加(同日)·全站切换 glm-5.3 落地(用户拍板「都换成 5.3 但要写成配置文件」)**:架构本就配置化(8 调用点全走 `settings.llm_model`,零硬编码),改两层:①config 默认 glm-4.6→**glm-5.3**(注释记决策依据与 5.3 特性);②max_tokens 按 5.3 思考肥瘦重校——**tutor 答疑 1024→8192**(思考+作答共吃预算,旧值答案必残缺)、**self_eval 256→8192**+零文本按「未评」兜底(同 grader 判别)、prep/research/grader/归位 8192→16384(note_writer 已是)。验证:config 改动触发 API 热重载,答疑 SSE 真跑通过(text_stream 自动滤思考块,答案干净);mypy 35=并行会话 `5a04e4d` 后的新基线(+1 非本次),ruff 零错。遗留:答疑首字延迟感知待真实使用体感
- ✅ **追加(同日)·旧 4.6 版 RAG 课退役(用户拍板「要新版旧版不要」)**:删 `rag-open-book-exam`(api+public 两份)+清 DB 残留(checkpoint_mastery 1 行/会话 1/轮次 2,M2 E2E 测试遗留);删前确认 `mastery._load_course` 对缺文件返回 None 有容错、全库无别的课件把它标先修(零悬空 depends_on)。验证:catalog 18 门旧课消失新课在位、review/due 正常、RAG 大纲 prepared:1 指向 5.3 新课。4.6 原件备份在 /tmp(重启即失,原件已删不可恢复)
- ✅ **追加(同日)·知识库版图对齐课堂大纲(用户拍板「vault 跟课堂里学的路线保持一致」)**:诊断=9/18 门课 `meta.topic` 解析不到 vault 目录(`Agent Harness`×6/MCP/RAG 检索增强/ACI四铁律——根因:归位机制 `find_todo_area` 只认 vault 待探行,大纲课不在待探里就漂成大纲 subject 名)+vault 结构停在 8-21(规划的 02-RAG/03-MCP 目录从未建)。调整:①**vault(独立 git 仓库,改动未提交待人过目)**建 `02-解析层/03-RAG/04-MCP` 主题目录(编号=学习顺序,多Agent 预留 05;上下文工程主题撤销=其空大纲已删)+各主题导览+待探骨架(**人工维护不镜像大纲**,想学的入口在生成中心点单)+导览/README/进度(复习看板标注移交 ai-classroom 学习台)/vault CLAUDE(分层轴修订:主题内自然结构=大纲 part,harness 四层保留)同步;②**12 门课 meta.topic 归一**(api+public 双份逐字节一致;验证:17 门课 topic 全部解析到真实 vault 目录,写回不再落根,catalog 分组收敛);③删 0 门课的上下文工程空大纲 `Agent上下文工程.framework.json`(2 份 material 保留);④退役 `parsing-layer-v2`(留大纲 course_ref 挂接的 9 节版 parsing-layer;无 DB 残留、无悬空依赖)。**遗留(范围外只提出)**:outline_prep 的 topic 归位建议加「大纲 part 兜底」(find_todo_area 未命中时按大纲映射),否则新主题后续点单出的课 topic 仍会漂;动 job_runner 前先对齐。**追加(同日晚)·大纲写入 vault(用户明确「大纲现在写入,课程学完再写入」)**:四主题各落一份 `大纲.md` **静态快照**(路线+每门 goal+先修链+已出课✓;文件名不含「待探」,刻意不进 想学的泳道/find_todo_area/待探勾选 任何管线,课堂侧调整后不自动跟随);既有 20 篇笔记、4 份大纲 JSON、写回闸语义(学完打卡→蒸馏→确认才写回)零改动
- ✅ **追加(同日)·vault 目录与大纲全自动同步 + harness 迁四篇(用户拍板「大纲和本地知识库目录一致,全自动跟随」)**:①新服务 `services/vault_sync.py`——theme_dir 绑定持久化进 framework JSON(解析顺序=别名表→绑定→归一名→新建;fw 的 domain 是「Agent 工程」类脏值,取首词+目录不存在回落 Agent)+篇目录=大纲 part(编号顺延不重排,part 消失→笔记撤主题根)+`大纲.md` 快照每次同步重生成(替代上条的静态快照,永不过期);触发点=outline_prep/request_research 出大纲后(job_runner)、大纲 PUT 落盘后(routes/outline)、pipeline --auto;②写回落点改篇制:material.topic=「领域/主题/篇」,find_todo_area 降级为 vault 不可用时的兜底(待探镜像方案就此作废);③harness 老区一次性迁移:16 篇 git mv 到四篇(起步 2/核心机制 11/工程化 3/实战 0,笔记归篇=跟随覆盖它的大纲课所在篇)+三层待探合并主题根+旧层目录退役+三层架构知识在 [[三层架构]] 笔记里不再是目录轴;④课件 13 门 topic 改篇制 + 4 处 vault source_notes 路径修复(含「Agent/harness/无编号」旧格式,api+public 双份);⑤vault 文档全量改口(00-harness导览重写/00-Agent导览/README/vault CLAUDE/进度/下次继续)。验证:17 门 topic 全解析到真实目录、source_notes 全存在、ruff 零错、mypy 净增 0、catalog 按篇分组齐整。遗留:fw domain 脏值只在解析层兜住(要干净值得动 research prompt);vault git 远程仍连不上(fetch 失败,待修 SSH)
- ✅ **追加(2026-11-04)·答疑 agent 认识全库课程与学习进度(用户提「融会贯通」)**:tutor 原上下文只有当前课全文,对系统其他 17 门课与学习状态全盲。三方案对齐后选**确定性注入**(融会贯通要求地图时刻在眼前,不赌模型记不记得调工具;弃 list_courses 工具=省 token 但挤占 MAX_TURNS 轮次,弃首条消息前缀=12 轮历史每问复制一份)。改动:①`progress.done_map()` 全库 done 一次查;②`catalog.student_course_map()` 一门一行「id|标题|主题|状态|大纲」(状态三档=已学完/学习中/未开始,与 completion() ready 语义对齐;轻量读法:课件裸 json+grade.jsonl 一次+done_map 一次,**不逐课调 completion(每次重读 grade.jsonl,17 门=17 次)**;40 门封顶);③tutor SYSTEM_PROMPT 增规则4「跨课融通」(已学搭桥/讲过指路复习/前置没学一句话提醒)+`build_system` 第三 block 追加在 cache_control 块**之后**(缓存前缀稳定,地图变化不击穿缓存)+`run_tutor(course_map="")` 默认参数;④chat.py 照「路由算好传入」分工。实测真问「MCP 和 tool use 关系」:答案引用地图原话「《MCP》未开始(0/11)」+搭桥已学完的《认识 Harness》+给三步学习顺序,课件引用/web_search/read_notes 全照常;2896 字符≈1.5k token/问。mypy 净增 0(自己引入的 `blocks: list[dict]` 补 `dict[str, Any]` 归零,基线 39),ruff 零错;测试会话已清(source=test 打点不进观测统计)。**用户拍板:粒度到课就够**——断点在 localStorage 不上报服务端,不做节级学习状态(勿再提)
- ✅ **追加(2026-11-04)·答疑区禁横向滚动+裸 URL 链接化(用户报)**:①横向滚动根因=长地址/长 token 在窄侧栏(w-80)撑破容器——消息容器补 `overflow-x-hidden`+`.chat-md` 加 `overflow-wrap:anywhere`(继承进内联 code,长地址就地折行)+`pre` 弃 `overflow-x:auto` 改 `pre-wrap`(窄栏代码长行折行不再横向滚)+用户气泡/「正在查」行补 `break-words`;②裸 URL→可点链接**零新依赖**(不引 remark-gfm,按 §2.1):复用 linkifyCitations 的文本节点改造位新增 `linkifyUrls`——字符集排除 CJK/全角标点(防「https://a.b/x。」把中文粘进链接)、尾部 ASCII 右括号**仅不成对才修剪**(Wikipedia 路径括号合法);markdown 真链接补 `a` 覆盖统一 `target=_blank`+`rel=noopener`。实测真问「LangChain 文档地址」:URL 渲染为锚点新标签开、与「课件第N页」按钮同条共存、scrollWidth==clientWidth 零横向溢出;6 条正则边界用例(句号/括号/查询串/中文粘连)全过。测试会话已从 SQLite 清掉(sessions+turns)
- ✅ **追加(2026-11-04)·答疑区滚动贴底跟随(用户报「发完要手动再滚」)**:根因=scrollTo 在 SSE 读循环里调,那一刻 React 还没把新 delta 提交进 DOM,滚的是上一帧内容高度,永远慢一拍——最后一段文字留在屏幕外。修法:滚动作移进 `useEffect([msgs])`(渲染提交后 DOM 已含最新文本再滚)+`stickRef` 48px 闸(用户在底部附近才自动跟随,流式长答案期间上翻阅读不被拽回,滚回底部自动恢复)+装载历史(恢复/切换/新会话)重置跟随态。实测流式全程 8 次采样距底部均 0px,结束 0px 零手动滚;oxlint/tsc 零错(9 warning 均既有);测试会话已清
- ✅ **追加(2026-11-04)·密钥配置集中到 config/(用户需求「所有需要 api key 的提到一个配置文件夹」)**:全项目唯一密钥文件 `apps/api/.env` → 仓库根 **`config/secrets.env`**(gitignore;ZHIPU/博查/Tavily/AnySearch 四 key + LLM_MODEL/KB_DIR 旋钮都在这),模板 `config/secrets.env.example` 随迁(git mv 保历史);config.py `env_file` 改指 `_REPO_ROOT/config/secrets.env`(经 `__file__` 绝对解析,job_runner 子进程不受 cwd 影响);research.py 无 provider 报错文案同步新路径;.gitignore 加 `config/secrets.env` 显式规则(裸 `.env` 规则罩不住新路径)。实测:settings 四 key 全载入、`./start.sh api` 重启就绪、ruff 零错、旧路径引用零残留(AGENTS/docs 历史条目不追溯改)
- ✅ **追加(同日)·公开远程仓库建立(`a193b4a`+`8e1ab7b`)**:`origin = git@github.com:wohaixiao-qds/ai-classroom.git`(**public**,浏览器代建);推送前置安全审计——①全 195 提交历史搜四个真实密钥片段零匹配、.env/secret 文件从未入库;②课件 36 文件移出版库(`a193b4a`,`apps/api/courses/`+`apps/web/public/courses/` gitignore——个人学习内容不公开,clone 后课程库为空属预期);③补 README(快速开始/密钥配置表/clone 即用:`pnpm install`→`cp config/secrets.env.example config/secrets.env` 填 key→`./start.sh`;类型产物已入库、data/ 自动建,无需额外步骤)。远程树 126 文件验证:零课件、唯一 secrets 相关是空值模板。**⚠️ 持久约束:远程是公开仓库,任何提交前先过一遍「这条内容能不能公开」;config/secrets.env 与 courses/ 永远不入库**
- ✅ 收尾已清(2026-08-24):gen-types 管线接上(catalog `59f15bc` + sessions `89b8ac1`;csl.ts 经决策保持手写——稳定的作者态契约,理由注记在文件头)、A4 多页可点(`5349427`)、B2 显示自评瞎编率(`6ecd5be`)、traces/ 移出 git(`05a0c2d`)。**P1/P1.5 收口完成**
- ✅ **追加(2026-11-17)·答疑收尾链双修+思考过程展示(仿 ZCode)**:①用户报「没输出但按钮还是停止」——根因=A6 自评裁判(5.3 思考常开后一次几十秒)挡在 done 之前+P6 后引用「第N节」不匹配自评豁免正则(只认「页」)→ 长答几乎每轮跑裁判;修=`routes/chat.py` final→done 立即发,自评+trace 挪 `BackgroundTask`(elapsed 改 final 时刻取,不含裁判),ChatPanel done 即收尾 cancel reader,stop 的 AbortError 不再误报「连接失败」,`_CITE_RE` 扩 `[页节]`(自评豁免恢复+观测 cited_rate 对 v2 不再恒 0);②思考展示=tutor 流消费从 `text_stream` 换原始事件迭代(thinking_delta→新 SSE 事件 thinking,循环结构/终止条件/工具回填零改动),路由转发,前端 `ThinkingBlock` 流式展开跟着长/答案落自动折叠/点开回看,**不落会话历史**(与工具调用同待遇,蒸馏/观测口径不变)。真跑:一次提问 1326 个 thinking 事件流式到达;顺序断言(monkeypatch 零成本)session→thinking→tool_call→delta→done→eval→trace 全过,报错路径不落后台账。**附带收益:5.3 首字延迟的黑盒等待变成看得见的过程**
- ✅ **追加(同日)·方案A:LLM 输出规范集中 `core/prompts.py`**(用户问「排版规范能否做成工具」,三案对齐拍板 A:prompt 片段库+统一 JSON 解析;C「LLM 工具化」被否=反 ACI+延迟翻倍):`JSON_OUTPUT_RULE`/答疑引用与窄框片段(CITE_COURSE_RULE 等)/`GRADE_OUTPUT_SPEC` 常量 + `parse_json_reply()`(剥围栏→括号截取→对象校验,提炼自 research 最健壮版),grader/self_eval/归位/research 四处归一;tutor SYSTEM_PROMPT 改点单拼装。**字节断言守恒**(tutor/grader prompt 逐字节不变,缓存前缀稳定),曾抓到提取时把 `.format` 双花括号写成单括号的真 bug;两处披露:自评纪律句统一口径、解析失败 trace reason 合并。**后续批改排版改版=改 GRADE_OUTPUT_SPEC 单点**
- ✅ **追加(同日)·3~8 门大纲依据注释(用户问「依据哪来」,互联网考据拍板「数字不变注释升级」)**:与在线课程模块数教学设计惯例带(各家 3~7/4~8/5~9)重合+MOOC 完课率随课程变长一致下降(Jordan 2014,HarvardX/MITx 数百门);粒度锚 8 分钟在 edX 视频参与度 6 分钟实证带上沿(阅读≠视频不硬换算);**Miller 7±2 是工作记忆块容量,不是门数依据,勿引**(Laws of UX 明文警告此误用,Cowan 2015 现代估计 ~4 块)。依据写在 `validate_framework` 数量闸注释,prompt 行不动
- ✅ **追加(同日)·批改展示排版 A+B(复述检查点改版落地)**:全网考据定模式(Hattie 三问缺 feed-forward+Glow&Grow+LLM-as-judge 原子判据+Khanmigo 教训「无论分数都给精准版」踩对混合式)定展示(Duolingo 结算环+逐题回顾)。`GRADE_OUTPUT_SPEC` comment 三行制(✓对在哪一条不空夸/✗缺在哪一条/→下一步一句行动);CheckpointOverlay `ScoreRing`(SVG 环+useCountUp 同帧驱动,pass=success/未过=warning,reduced-motion 直达)+`parseFeedback` 三段行(无标记行回退整段 markdown,兼容旧 trace/服务异常)+复述对照左右分栏(sm:grid-cols-2 窄屏堆叠,Collapse 可折叠)+结果态弹层放宽 max-w-2xl;note_writer 落笔记取 comment 首行(旧单行 trace 兼容)。真跑 95 分 pass:模型严格三行制,折叠/CTA/高亮全过(临时课件克隆,清理后全库扫描零残留)
- ✅ **追加(同日)·课件来源溯源(纯前端,用户问「源[2]是什么」暴露缺口)**:阅读器节后渲染 `meta.sources`「来源」清单(标题外链+URL 副行;**旧迁移课无 sources 不渲染整节**,13/17 门有),正文「源[N]」`linkifySources` 链化锚点跳转+高亮 1.6s(递归文本节点含 strong/em 嵌套,p/callout 接入;来源节在 sections 数组外,TOC/学完进度/深链零影响)。真课 11 处引用全链化实测
- ✅ **追加(同日)·退役 harness-external-layer(同名旧版 8 源,用户拍板「保留新版」)**:保留 recognize-harness-software-layer(11 源);编排循环 depends_on 改指新版(双份)、Agent-Harness 大纲 course_refs 移除旧 id(保留 recognize+harness-01 挂接)、双份课件删除;DB 零残留、全库悬空依赖扫描零。**修浏览器标签页标题写死**(index.html「harness 是什么」P1 遗留,用户报「和我目前的对不上」):改「AI 课堂」+ReaderPage 动态 `document.title`=课名·AI 课堂,离开恢复站名,实测生效
- ✅ **追加(2026-11-17 晚)·课程库书架两层导航+学习台合一(IA 定稿)**:用户提「学习台内容太多/每次学习都得从课程库点」,三案对齐拍板 A 合二为一——①课程库=书架(封面卡:书脊高光/哈希恒色/篇课数/进度条/▶当前课+**继续读直达**),点书进 `/books/:topic` 书页目录(篇→大纲课→挂接课件平铺真实标题+点单备课+8s 轮询),OutlineToc 退役(「已挂 N 门」手风琴与行名≠课名的双歧义随两层结构消失);②学习台退役(`/` 重定向 /courses,HomePage/OutlineToc 删),今日横条(断点继续学+到期复习 23 张限高滚动)常驻学习页顶,导航四项→三项(学习/生成中心/观测),「想学的/刚冒出的」迁生成中心;③vault 侧考据顺手修 index.html 写死标题。浏览器两层实测+截图
- ✅ **追加(同日)·多挂章行内推进(割裂根治)**:用户报「学完 04 后 05 的自我学习闭环与 state 侧信道不知道学哪,割裂」——根因=行级「读任一片整行✓」把互补兄弟片孤儿化(state 已读→05 整行✓→游标跳 06)。拍板 A:行级✓改**全片读完**,游标=第一门含未读片的行→行内第一个未读附件,书页行卡亮「已学 x/y 片」;封面同语义。bonus 发现:harness-01(重复版本片)拦游标→从大纲 refs 移除(课件/4 门先修链/5 次答疑历史全保留,可逆)
- ✅ **追加(同日)·内容归一:两代内容体系收编完成(用户拍板「从根源解决」)**:归档 6 门旧课(harness-01/ACI/工具层/工具粒度/自我学习闭环/state 侧信道→`data/archive/2026-11-17-内容归一/`),组整合材料走 cached_material 命中**零联网**派 outline_prep 重出 2 门整合课(03《工具设计:从 ACI 铁律到粒度权衡》4.5min/7 节/45 块/4 检查点/10 源,人审通过;05《状态与学习:harness 替无状态模型记账》7 节/43 块/5 检查点/10 源,先修=书内 01+04 **倒挂修复**,待人审);先修清洗 8 文件+DB 残留清零+悬空 0;**防重闸教学**:同名旧片在盘会拒单,先退役再点单;**材料组装配方**:旧课 v2 节文本→groups(points 带 source_id 挂真实来源+手写课挂权威博文出处),写 `{slug(topic)}.{slug(课名)}.material.json` 缓存即被 outline_prep 复用
- ✅ **追加(同日)·归位一行一片收紧**:attribute_all 已挂接的行不再堆新片(候选转未归位,reason 注明「已有课件」),写回合并防覆盖(旧 refs 不因本轮丢失)——多挂堆叠的根从此堵住;真跑「没有待归位的课件」符合预期
- ✅ **追加(同日)·vault「一本书」融合(用户拍板定位「vault=项目本地生成记录学习路线」)**:一章一篇章笔记——03 融合篇《工具设计》并 ACI+工具层两篇;04《上下文压缩与记忆》并 08 年老三篇(桌子模型/四级优先级/缓存验证法/生产三件套/分场景/默写史全保留,354 行);无章散件 4 篇(Skill设计/系统提示词设计/错误回收/终止条件)入 `99-存档/`+索引;导览按书八章重建(章↔笔记一一对应);探索存档《归档-安全关卡与谁在学》(整合课未单独成节的两节原文)落 sources/_index;**CLAUDE.md 会话续接断链修正**(下次继续/进度已删,续接归学习台,历史在 vault git);vault git 全程版本控制删改可恢复。**教训:并行整理风险——vault 笔记被用户 Obsidian 同期编辑(上下文压缩与记忆蒸馏笔记等),动 vault 前先重 ls 盘面,勿用旧读数**
- ✅ **追加(2026-11-17 晚)·老课四宝石制度化(用户问「老 Claude 怎么出课/有什么可取」,考据 vault CLAUDE.md 教学契约+git 收官史后拍板全收)**:对照新管线四项未吸收优点——①**坑是主菜**(每节必配 warn callout:症状/为什么/怎么避免,老笔记最值钱部分)②**开发落地三问**(触发场景/怎么决策/怎么实现,每节收尾必答)③**现成件**(全课至少一处真实库/参考实现清单,禁编造)④**grader 反背诵条款**(只背定义/复述原文上限 60 判不过,说清「什么时候用怎么选」才给 70+)——落 `core/prompts.py` 常量(PITFALL_RULE/DEV_LANDING_RULE/OFF_THE_SHELF_RULE + GRADE_OUTPUT_SPEC 标尺),prep `_SHARED_STYLE` 挂载(全量/续写两套 prompt 经占位共用);ruff/mypy 基线零增,format 闸验证过。**真跑效果验证留待下次自然点单**(无待出课,不专为验证烧一门)
- ✅ **追加(同日)·课堂三栏占比可拖拽(用户需求)**:在线课堂左右栏宽手动设置——`ColResizeHandle` 自研拖拽分隔条(零新依赖,mousedown/mousemove/up+body select-none),左柄调目录宽(160~400)、右柄调答疑宽(260~560),双击手柄复位该栏默认(224/320);`reader-panels` localStorage **全局持久化**(跨课一致,非按课);中栏 flex-1 自适应、正文保持 max-w-2xl 居中(阅读宽度是刻意设计);md 以下 TOC 隐藏手柄同步隐藏。实测:拖拽/刷新保持/双击复位/右柄向左拖=变宽全过
- ✅ **追加(同日)·老待探反思框架制度化:大纲课弱点归因(用户拍板)**:老找课的过滤器「这是在弥补模型哪个弱点?」升级进大纲设计——`_FRAMEWORK_PROMPT` 的 why 字段从泛泛「为什么值得学」改为**弱点归因**(归约到模型失能:无状态会忘/输出会错/窗口会满/没有执行权需要代理,或同级;硬规则加「归约不进去的课不值得单独存在」);渲染三处:vault 大纲.md 快照加「弱点归因」行(vault_sync 两处格式)、BookPage 章卡「↯ 弥补:…」行、OutlinePanel 经 API 透传(why 本就在白名单)。**坑记:vault_sync 只管 `^\d+-` 编号目录**——自建的「99-存档/」被当成消失 part 清理(4 篇撤主题根),改无编号目录名「旧课散件存档/」+同名索引后 sync 稳定;动 vault 目录结构前先读 _sync_parts 判定规则
- ✅ **追加(同日)·历史 trace 无据标签重算(用户拍板)**:旧正则盲窗(11-02→11-17)产生的 36 条「无据长答」历史冤案按新正则(`[页节]`)一次性重算——31/69 条修正(cited_pages 单向只增,grounded 单向翻正),改前备份 `data/archive/…/tutor.jsonl.bak-20261117`;**无据长答 36→9,观测页数字恢复真实**;A6 裁判口径不变(fabricated 依旧 0——这批从来没有真编造)。05 整合课人审通过收编,内容归一两章(03/05)全部落地
- ✅ **追加(同日)·normalizeBold 规则 0.5 跨句贪心误伤修复(用户报「课件内还有**」)**:整合课 8 处字面 `**` ——根因两层:①规则 0.5 的 `[^\n]*?` 非贪婪回溯**能吞掉跨段长文**(「名字:**ACI…定义:**新型软件」被误配对挪位,粗体全错),收紧 inner 限 30 字+禁内嵌冒号(保留招牌句修复能力,回归测试过);②新形态「：**中文句子。**」(冒号后开/句号后闭)micromark 判废(实测 4/4 字面,全角半角皆然)→ 新规则 0.6:closer 挪到句末标点前(`:**X**。` 中文粗体惯例形态)。验证:esbuild 转译真跑 normalizeBold 全课 17 块配对平衡、浏览器正文字面星号残留 0
- ✅ **追加(2026-11-18)·双 key 切换真修复(429 实测暴露两层 bug,首版切换是纸面的)**:①重试复用切换前捕获的旧 client(主 key)——修:`_guard` 收工厂函数,重试重新解析 client;②**anthropic SDK 的 stream 构造时不发请求**(HTTP 在 __enter__/首迭代才发起),构造期守卫永远兜不到 429——修:`_StreamWithFallback` 流代理,切换判定挪进 `__enter__`,主 key 失败切备用重入新流,属性/迭代/退出全代理。真跑 429 实测:切换行打出+重入成功+答疑出答案;三场景单测(防回归「重试必须走备用 client」)。**运维注意**:切换是进程内持久的(不回头撞),主 key 限额重置后需 `./start.sh api` 重启回主 key;**英文泄漏(glm-5.3 把英文推理写进正文)在两把 key 上都间歇出现**(次日重置后主 key 真跑也英文开头过)——是模型行为波动非账户差异,中文规则已缓解,真实使用持续观察
- ✅ **追加(同日)·答疑语种与元话语规范(备用 key 实测暴露)**:SYSTEM_PROMPT 规则 5 改正向措辞——「回答始终以面向学员的口吻直接书写,只包含学科内容本身,不包含规则编号/合规说明/自我检查过程或任何英文推理;全程简体中文」。实测三轮迭代:元话语消失,中文输出达标(备用 key 有波动,主 key 稳定)
- ✅ **追加(同日)·划词提问(用户想法:看课件遇不懂名词选中即问)+双入口加固(实测反馈「浮钮被划词翻译软件悬浮窗遮盖」)**:阅读器 `SelectionAsk`——选中正文 2~200 字 → 选区上方浮出「💬 问 AI 老师」→ 一键接种子(`我在课件里看到「XX」,这个概念/名词不懂,请用零基础能懂的话解释`)进右侧答疑自动发送;正文区(article)外不弹;任何滚动即隐;fixed 定位取选区矩形;ChatSeed.checkpoint 改可选(划词无检查点上下文,复述卡联动不受影响)。**遮盖修复**:系统级悬浮窗压浏览器窗口,z-index 无解——加**面板内提示条**(ChatPanel 输入区上方「选中了『XX』[解释一下]」)作遮不住的安全入口(页面内部元素永远可见),浮钮降级为快捷方式;滚动隐浮钮时提示条保留最近一次选中;两入口共用 selQuestion 构造。真跑:「KV 缓存」长剧类比+衔接已学笔记、「占位」双类比(此处原图略/图书馆牌子)+引课件第3节,全中文零反问 ✓。**教训:给浮层入口设计先问会被什么遮——系统悬浮窗(划词翻译/输入法)永远压浏览器,floating UI 必须配页面内后备入口**
- ✅ **追加(2026-11-18)·答疑 agent 三抽屉落地(用户用「策略级/经验级/规则级」框架拍板全做)**:①**策略级**——规则 8 升级「不瞎编(不确定就先声明)」:查不到先声明「课件没讲、我不确定」再给推测(标「我猜的」),不许拿顺口说法悄悄填缺口;②**经验级(agent 教训账本)**——`data/agent_lessons.md`(人可审,删行=撤销教训;loader 跳 # 行与 `<!-- -->` 块注释),自评判 fabricated 自动追加「[待审]」候选,`build_system` 注入(地图后,上限 20 条,不破缓存前缀)——**agent 侧自我学习闭环首次落地**(此前只有学员侧);③**规则级(假引用门禁)**——`services/citation_guard.py` 纯文本毫秒级:「课件第N节/页」对 course_text `[第N节]` 标记、`[N]` 标号对链接数,违规→done 前补正 delta(流式无损)+trace 记 guard_violations。单测 5+3 例全过,E2E 正常问答零误伤。**取舍:缓冲预检(攒完再验)杀流式,弃;事后补正=学员见错句但立即被纠**。同日:批改等待活体信号(按钮 spinner+秒数走字,`2b1bf2f`)
- ✅ **追加(2026-11-19)·答疑底料节级窗口(用户问「课件全文都放上下文是不是浪费」拍板 A 方案)**:全文 4~8k token 每问全价(Coding Plan 限额按 token 计,且智谱端点 cache_read 恒 0 缓存失效)——`course_text_of(section=)` 节级窗口:当前节±相邻节全文+**全课目录常驻**(跨节指路不瞎编),窗口外只有标题;引用规范同步收紧(只引窗口内,窗口外如实说「没带那节」,citation_guard 全文比对在路由侧不受影响);无 current_page 时全文兜底。实测省 45%(6043→3365 字符),双模式 E2E 过。read_notes 澄清:读 vault 不是课件(课件走 system 底料)。**缓存真相:智谱端点 cache_read 恒 0(cache_control 被忽略),全文模式「缓存友好」的前提在本端点不成立——换端点即恢复**
- ✅ **追加(同日)·答疑「永挂」事故三连修(用户报:停止后重发一直思考中)**:排查链——turns 铁证(停止的提问悬着无回复)→绕开服务直探全通(create 1s/大输入 stream 0s)→**根因=API 服务进程跑一天的 httpx keep-alive 连接池坏死**(中转单方面掐空闲连接,客户端拿死连接干等;新进程全通、服务进程全挂,与 key 额度无关——主 key 直探一直通,服务也从未切过备用)。三修:①`_build` 挂自定义 httpx client:`keepalive_expiry=60`(连接保鲜,少碰陈旧连接)+`max_retries=2`(掐断自动重连)——治本;②**答疑占位消息提前到发送瞬间**+「思考中… · Ns」秒数走字(此前首响应头前 20s+ 面板全白,活体信号缺失是用户误判卡死的另一半);③连续 user 历史(user,user,user 三连)实测端点接受,非问题。**运维口径:答疑秒数在走=活着(5.3 思考 30-60s 正常);全白/秒数停=真挂,先 `./start.sh api`**。fallback 三场景单测回归过
- ✅ **追加(2026-11-20)·Agent 架构审查首批正确性修复(用户已对齐)**:①tutor 当轮上下文分块合并,当前节/检查点不再覆盖已学词表和进度增量;②citation_guard 从完整课件结构生成章节索引,模型仍用节级窗口,窗口外真实章节不再误报不存在;③job_runner 终验失败/大纲缺课/未知类型统一进入 failed,成功发布才记 done,软着陆产物保留。新增标准库 unittest 离线回归 14 项(含上下文 16 种组合、SSE 引用校验、临时 SQLite 任务状态),全部通过;ruff app+tests 通过,测试文件 mypy 通过,app mypy 与 HEAD 逐项对比仍为 39 处/9 文件,新增 0。未调用真实模型或写入学习知识库。
- ✅ **追加(2026-11-20)·Eval 基础修复(用户确认四方向)**:①学习状态改读 SQLite `learning_grades`,一次事务导入完整旧批改轨迹并从 mastery 补回历史 pass,完成判定/课程地图/已学词表/最近批改/笔记批改底料不再受全局 Trace 窗口影响;新 `source=test` 批改不入学习结果或复习排期,保留 raw_score/tutored 区分模型评分与辅导保底。②共享 `TraceRun` 按 run_id 追加 started/progress/finished/assessment,答疑执行先落盘后后台补评,调研/备课/批改异常或取消也记终态,进程退出无终态显示 interrupted;真实循环次数、模型/代码/提示/工具/初始上下文哈希与本地快照可复盘。③弃「引用或搜索=有据」,工具行为/引用存在性/语义证据支撑分别计量;高风险全评、其他固定 20% 抽样,裁判纳入实际成功工具返回与会话上下文,未评原因/覆盖率/裁判 token 耗时独立可见;旧记录状态与证据结论保留未知。④自动教训只入 pending,包含旧 `[待审]` 行,观测页可编辑确认/拒绝/撤销,确认后下一问生效;保留人的旧手写规则。Eval 页新增四类执行轨迹、引用/重教违规、正确分母与错误重试,类型由 OpenAPI 生成。新增 `apps/api/evals/` 9 个固定场景+参考/反例+人工 rubric,`scripts/eval_agent.py` 离线检查记录输出,缺人工标签返回未评(退出码 2),自检不冒充真实模型成绩。验证:38 项 unittest/ruff/测试与评测脚本 mypy 通过;app mypy 对干净 HEAD 为 39→19,新增 0;web lint/build 通过(存量 warning);隔离浏览器验证确认/撤销/来源过滤/失败与取消/503 重试,实际 CSS 480/768/1024/1440 无横溢。**限制**:线上裁判仍与答疑共用模型,9 个种子场景尚未采集真实模型输出与人工标注,不宣称质量准确率;当前内置浏览器最窄实际 CSS 480,375/414 未完成实测。断连测试初版的替身提前退出作用域,曾误走真实答疑路径并写入 3 条 mock-session 孤立提问;已按固定会话/课件/内容/行 id 精确清除,复查残留 0,并给所有测试库与模型入口加隔离兜底(未模拟调用立即失败),修复后全量通过。真实课程/批改/掌握度/知识库未改,临时预览已关闭。
- ✅ **追加(2026-11-20)·备课恢复与规划兑现验收(架构审查续项)**:规划保留 covers,建课时原子保存 `data/research/<course_id>.plan.json`;恢复加载原节 id/顺序/测验要求,已恢复规划撤掉 init/submit 工具,坏规划明确报错。旧半成品缺规划先补交且必须保留已有节 id;建课后规划锁定,write_section 拒规划外 id 并按原序落盘。自查与收笔终验共用规划对照(漏节/重复节/顺序/计划测验缺 pass_rule 均打回),结构有效不再等于交付完整。修断连测试替身生命周期,覆盖完整 SSE 消费。新增 8 项临时目录+模型替身回归,全量 46 项 unittest/ruff 通过,改动模块与测试 mypy(`--follow-imports=silent`)通过。限制:材料 covers 仍为写作约定,不代表语义覆盖或事实核验;未跑真实模型/发布/知识库写入。
- ✅ **追加(2026-11-20)·后台任务与产物稳定绑定**:三类任务共用 SQLite `job_bindings`(稳定 binding id/预留课件 id/原料快照与哈希/规划哈希),执行尝试用 catalog_actions.id 单独传子进程;重复 queued/running 事务去重,状态按尝试 id 回写,取消终态不被旧进程复活。prep 建课采用预留 id,每轮/写节检查尝试有效性;重试定位绑定课件,材料或规划变化/丢失明确拒绝,旧任务仅在来源或领域可核对且唯一时迁移。大纲同名课按任务领域隔离,取消保留骨架与规划,未交付绑定产物不进入课程库/发布;日志与 PID 按尝试分离,异常退出任务可在再次提交时校正并恢复。新增 16 项离线回归,当前全量 62 项 unittest 通过;本轮 13 文件 Ruff/定向 mypy 通过。未启动真实模型、后台生成或知识库写入;材料变化后的显式重建/差异审阅 UI、真实模型评测基线仍待后续。
- ✅ **追加(2026-11-20)·审查剩余三项实施**:①原文→原料→课件证据链:Research 用实际抓取正文生成快照/摘录偏移/指纹,伪造摘录与坏快照打回,每份新原料额外做一次模型语义初审(失败明确未审);Prep 确定性带入来源编号与证据索引,块关联 evidence_ids,拒未知或已标不支持的原料引用。旧材料不补造验证;旧半成品按 URL 恢复丢失的来源编号。阅读器按节展示原文依据;只读 `audit_evidence.py` 对实际正文另审,表格图注也纳入,人工标签绑定内容哈希,全量人工确认才退出 0。②通用领域适配:why 改具体学习障碍/应用问题,模型弱点只用于适用的 Agent 课程;稳定理论不再强制近一年,新领域使用自己的 vault 目录与导览链接,旧主题绑定保留。③契约与文档收敛:Pydantic 唯一 CSL 结构源,复用现有 openapi-typescript 生成 csl.gen.ts,csl.ts 只留别名/视图函数;漂移检查串入 lint。README/有效开发规范/Agent 现状同步书页架构,阶段计划保留历史语境。新增 18 项离线回归,全量 **80 项 unittest 通过**;Ruff/定向 11 文件 mypy 通过,app mypy 对干净 HEAD 为 19→19、新增 0;web lint/build 通过(9 个存量 warning及包体提示),故意改生成产物后漂移检查如预期失败、恢复后通过;9 项评测器自检通过但未跑真实模型。隔离 CLI 验证未审=2/人工标签示例=0且原件未改;隔离浏览器验证来源跳转/旧课不渲染/键盘折叠/实际 CSS 480 与桌面无横溢。**限制**:未做真实模型端到端或人工真值集校准,同源模型初审不代表事实正确;旧课未回填证据;375/414 未实测。验证未改真实课程、学习库或知识库,未新增依赖,预览已关闭。
- ✅ **追加(2026-11-20)·harness eval 真课审阅后修补**:样课纠正 SWE-agent 成绩的过度因果归因、系统各占一半、案例泛化及评分器可靠性排序,补对照实验完整示例与应用设计题(6节/47块/5测验),源与前端副本同步,入口先修清空。证据初审改为最多4条/约2万字符一批、16384预算,成功项保留且失败项单独重试一次,记录 stop_reason/块类型/文本长度/格式或调用错误与累计用量;未完成仍未审。两条任务入口传大纲目标与权威先修上下文,目标应用题及判分标准进入持久规划并由自查/收笔共同验收;旧规划只补验收约定,不改原节序与覆盖,目标变化拒绝续写。先修按显式 refs 或同领域大纲 id 解析,空列表也覆盖模型建议。新增11项离线回归;未调用真实模型、未写学习库或知识库。限制:目标题与实际目标的语义对齐仍需审阅,已有原料保留历史快照,证据状态不冒充复审通过。
- ✅ **追加(2026-11-20)·课件发布可信度门禁**:新增 services/publication.py,原文快照/来源URL重验+最终全部内容块(含图表/闪卡/测验标准)独立调用审查,不携带原料裁判评分,绑定课件全内容哈希与独立报告;未审/部分支持/冲突/缺报告/内容变化均禁止发布,明确区分自动通过与人工复核。后台和CLI共用,最多两轮定点修订,审查服务失败不让作者猜着改;发布函数二次强验,逐文件替换且保留旧发布版。新骨架标 publication_required,未过审不进入课程库/大纲已出计数/答疑课程地图;旧课兼容但阅读器明确显示尚未按新规则审查。裁判模型可经 EVIDENCE_REVIEW_MODEL 配置(默认同模型独立调用)。新增14项发布回归,全量105项通过;定向Ruff/mypy与web lint/build通过(现有warning)。真实重调研在work/harness-eval-reviewed-20261120隔离执行,不触发vault同步;已观察原料连续撞16K预算,material阶段提高32K并记录停止原因/块类型/文本长度,实际验收结果待本轮运行结束补记。
- ⚠️ 长期记账(不阻塞 P2):①A4/ChatPanel 的 typescript-reviewer 屡被中转挡,恢复后补(现以 §3.1 自查+浏览器实测代替);②A6 局限(2026-11-20 更新):引用存在性门禁只查存在,语义支撑仍需裁判与人工校准;当前同源模型审查信号不能当准确率,固定用例真实输出与人工标签待积累;③dev 服务器(API :8100 / web :5273,原 5173 与他项目冲突已改)会话结束需重启;④4 门调研管线前的手写课(ACI四铁律/harness 是什么/自我学习闭环/工具粒度设计)无 meta.sources,来源溯源对它们不渲染——补来源=内容审校活,非机械回填,暂缓(2026-11-17 晚:四门已全部退役归档,本条随之关闭)

---

## 常用命令（代码初始化后生效）

```bash
./start.sh          # 一键起前后端(旧进程自动先杀再重启;./start.sh api|web 单独重启)
cd apps/api && uv run ruff check app && cd ../web && pnpm run lint   # lint
pnpm -C apps/web gen-types   # OpenAPI → TS(需 API 已启动)
pnpm -C apps/web gen-csl-types   # 静态 CSL Pydantic → TS(无需起服务)
pnpm -C apps/web check-csl-types # 生成一致性检查,已串入前端 lint
uv run --directory apps/api python -m unittest discover -s tests -v
```

## AI 工具差异说明

- **Claude Code**：详见 `CLAUDE.md`（子 Agent 调用约定）
- 其他工具：遵守本文件；审查用 §3.1 清单代替
