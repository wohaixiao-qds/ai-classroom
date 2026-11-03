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
- ✅ **追加(2026-11-03)·批改百分制(`grader` 重写,用户规格)**:「按输入打分,<70 要求重新复述或问 AI 老师后再复述就过;≥70 保留答案+精准版并判过」——①prompt 评分标尺(85+全对/70-84 核心说清/40-69 漏关键/0-39 说反),输出 score;②服务端 score≥70 判 pass,<70 判 fail;tutored(问过老师)保底 70;③trace/note_writer 落 score+precise(答案与精准版都进笔记);④overlay 得分徽章+非 pass 双钮(问老师/重新复述);⑤双真跑:弱答案 30 分 fail(点评准确点名漏了生成端与双记忆)→tutored 重试 70 分过。中转抖动致两次 502(重试机制吞掉一次)
- ✅ **追加(2026-11-03)·批改 502 真因修复:思考模型 max_tokens 预算(`grader`)**:排查批改间歇 502——直接探中转 5/5 全通(2~3s),排除中转;真因=GLM 思考模型的思考块**也吃 max_tokens 预算**,批改 1024 被思考烧光→零文本→JSON 解析失败→「返回格式异常」502,间歇性=思考长度随 prompt 浮动。修复:8192(与 prep/归位同档)+零文本时亮 stop_reason 与块类型。教学教训归档:bg-llm-job-ops 记忆
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
