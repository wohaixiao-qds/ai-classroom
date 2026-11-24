# 教学 Skill 借鉴优化开发计划（2026-11-24）

> 背景：调研了 GitHub 上四个高质量教学/课件类 skill 仓库（详见附录 B），逐一读过 SKILL.md 原文。本计划把「值得借鉴的」转成任务，把「不借鉴的」钉死防止复议。**本次仅生成计划，未修改业务代码。**

---

## 0. 总判断（所有任务的依据）

- 项目强项 = **程序闸**（规则落进模型够不着的判定层）；四个 skill 仓库的共同弱项 = **纯 prompt 自觉**（纪律写在那，模型听不听随缘）。
- 借鉴方向：**只借纪律内容与理论锚点，套进已有闸体系；不借执行机制。**
- 优化重心：**「考核→学习闭环」这条线**（④批改层 + ⑤学习闭环层）。备课侧闸已比所有参考实现严，大纲层已独立收敛到教育正统；skill 库的精华（检索练习/间隔/误解记录/迁移考核）全部落在学习侧——那是当前薄的一侧。
- 大纲设计理论对照已验（附录 A）：goal 可验证=Mager 行为目标、先修 DAG=Gagné 学习层级、检查点先于正文=UbD 逆向设计、规划兑现=建构性对齐。合理性站得住。

**开工前置：备课线程序闸门验证收口。** T1 动 `core/prompts.py`/`_SHARED_STYLE` 与 validator，与在途验证同域；唯一例外是 T2（文件面与备课线零交集，见 §3）。

---

## 1. 不借鉴清单（拍板记录，防止复议）

| 项 | 不做的理由 |
|---|---|
| `/teach` 的 MISSION.md 学习动机机制 | 大纲 goal 已覆盖「可验证禁了解/熟悉」；学员动机建模是新维度，无真实痛点驱动 |
| education-agent-skills 的 evidence_strength 元数据 | 自报证据强度是给无闸系统用的；G2 逐块审查比它强，不需要 |
| 间隔序列 `[1,3,7,14,30,60]` 调整 | Cepeda 317 实验结论恰是「无万能公式」，现固定扩张是诚实选择。备忘：将来收到「怎么老在复习旧的」反馈，标准答案是 Kornell & Bjork（2008）——学员体感是反信号，别拿体感当间隔效果评价指标 |
| lesson-generator 的 6~8 课紧凑预算 | 已按证据密度定块数（块/点比），两套预算混用会打架 |
| ppt-master 的 PPTX 输出 | v2 书页形态已定，幻灯片已退役。仅其 SKILL.md 执行纪律七条（阻断闸/最浅拥有层修复/禁投机执行）留作 prep 循环下次改造的对标范文 |

---

## 2. 任务分解

### T2 错因结构化（优先做 · 总开关）【1~2 天】

**借鉴来源**：`/teach` 学习记录判据——「误解被纠正 = 最高价值记录，能预测相关主题未来的绊脚石」「Coverage is not learning」。
**现状缺口**：grader 的 comment 已经产出「✗缺在哪一条」，但这个信号吐出来就蒸发在文本里——不参与复习排期，不进答疑上下文。复习卡把学员拽回来重测，却不告诉他「上回你漏了啥」。

- **T2.1** `core/prompts.py` 的 `GRADE_OUTPUT_SPEC` 增结构化 `gaps: []` 字段：每条一句、点名具体缺的点（从「✗缺在哪」纪律平行提取）。comment 三行制不动，机器可读输出平行加一份；旧输出无 gaps 需兼容。**GRADE_OUTPUT_SPEC 是批改排版的唯一改动点**（既定设计红利，本次正是吃这个红利）。
- **T2.2** SQLite `learning_grades` 加列 `gaps`（JSON 数组文本；ALTER TABLE 增量迁移，历史行空值兼容）。`source=test` 不落学习结果的既有机制沿用。gaps 存最近一次尝试（强 pass 后为空）。
- **T2.3** 消费三处：
  1. **复习卡**：`due_reviews` 带该检查点最近一次 gaps，阅读器到期卡显示「上次漏了：…」（空则不显示）
  2. **答疑**：`ChatRequest` checkpoint 上下文补传该检查点最近 gaps，`run_tutor` 注入「学员上次复述漏了 X，请针对性引导」
  3. **观测页**（可选）：批改卡展示 gaps
- **验收**：双真跑——弱答案批改 → gaps 落库 → 回拨到期 → 复习卡显示 gaps → 复述卡「问 AI 老师」→ tutor 上下文确认收到 gaps；模型替身 unittest 覆盖 spec 解析与兼容；Ruff / mypy / 全量 unittest 过。
- **注意**：动 DB 前导出受影响行（项目惯例）；测试不污染真实学习数据。

### T1 备课纪律包（捎带 · 半天）——**待备课线收口后动**

**借鉴来源**：`/teach` 测验反出千规则 + lesson-generator 的先例后抽象、来源真链冒烟检查。

- **T1.1** `QUIZ_FAIRNESS_RULE` 常量进 `core/prompts.py`，挂 `_SHARED_STYLE`（全量/续写共用）：quiz 选项字数尽量等长、正确答案位置随机分布、禁止用格式或顺序泄漏答案。
- **T1.2** `_SHARED_STYLE` 加一行「先例后抽象」：抽象概念首次出现前必须先给具体例子（exemplary 申报机制照常适用）。
- **T1.3** 来源标号闸（本批唯一的程序闸）：validator 新增检查——正文「源[N]」标号必须 ≤ `meta.sources` 数量（现状：悬空「源[9]」静默变死链，无人校验）。**落地前先跑全库扫描定级**：存量全过则 error 硬闸；有违例则 warning 起步并逐课修复。
- **验收**：全库扫描报告；unittest 直测闸；Ruff/mypy 全量过。效果验证 = 下次自然点单，**不专为验证烧一门课**。

### T3 书末综合复测 + 应用型考题【2~3 天 · 动前需三问对齐】

**借鉴来源**：lesson-generator 的 cumulative review + UbD 迁移考核（performance task = 新情境应用，非复述）。两者合流：都是「考核从背出来到用出来」。

- **T3.1 应用型考题纪律**：prep quiz 写作纪律升级——检查点题面尽量情境化（「遇到 X 情况你会怎么排查/怎么选」），判分标准写明「能应用到新情境」而非复述原文；与 grader 反背诵条款咬合（纯背定义/复述原文上限 60 已有）。
- **T3.2 书末综合复测**：一本书的全部课程读完 → 学习台/书页出「综合复述」邀请 → 从**全书**检查点抽样 3~5 个组段复测 → 复用现有 `/grade` 与 mastery 落库链。**零课件/schema 改动，纯学习台功能**——比 lesson-generator 的「课程内嵌 final quiz」更适合本书架结构（书=大纲，课会增长，内嵌 final review 会过期）。
- **动前对齐三问**（共创区，勿擅自拍板）：
  1. 抽样策略：薄弱优先（低掌握度/到期未测）/ 均匀跨课覆盖 / 混合——**推荐薄弱 + 跨课覆盖**
  2. 入口形态：书页顶部横幅 / 学习台卡
  3. 复测结果是否进掌握度排期：**推荐进**（pass 照常进位，fail 不额外惩罚、给重读对应节的指路）
- **验收**：隔离课件全链真跑（组卷→复测→落库→排期联动）；unittest。

### T4 答疑提示阶梯（最后 · 学习区闸，动 agent 循环）

**借鉴来源**：education-agent-skills 的 `worked-example-fading-designer`（渐隐式示范：全示范 → 半提示 → 独立完成）。现状：tutor 引导是单档的（一次到位）。

- 方向：单档引导 → L1 点拨 / L2 半示范 / L3 直接讲，按同检查点卡壳次数升级。
- **动手前须专门对齐**（§1.4 学习区闸，不踩线）：卡壳判定在哪一层（路由层计数 vs 会话内轮次）、分档 prompt 注入位置、与三抽屉/侧信道/划词提问的交互。工作量待对齐后评估。

---

## 3. 顺序与并行约束

```
T2（先做,总开关）
  → T1（待备课线闸门验证收口;动 prompts.py/validator 与在途验证同域）
  → T3（动前三问对齐）
  → T4（学习区闸,专门对齐）
```

- T2 文件面（grader / learning_grades / reader / tutor 上下文）与备课线**零交集**——若收口前确需开工，仅 T2 可先动，commit 前必查 git log（并行会话纪律）。
- 每任务完成：更新 AGENTS.md 当前状态节 + Conventional Commits + 全量回归。

## 4. 全局验证纪律

- 离线优先：unittest / 模型替身；prompt 纪律类改动的真跑效果**待下次自然点单**，不专为验证烧一门课。
- 动 DB 前导出受影响行；测试用 `source=test` / 临时课件惯例，不污染真实学习数据。
- 提交前过 §3.1 自查清单；公开仓库红线：课件/学习数据/secrets 永不入库。

---

## 附录 A：大纲设计理论对照表（2026-11-24 已验，合理性结论）

| 大纲设计元素 | 对应理论 | 判定 |
|---|---|---|
| goal「可验证，禁了解/熟悉」 | Mager 行为目标（1962）：目标必须可观察，模糊动词禁用；Biggs：不可考核的目标无法锚定评估 | ✅ 正统 |
| prereqs DAG + 入口课无前置 + Kahn 排序 | Gagné 学习层级（1965）：上位技能以下位掌握为前提 | ✅ 正统 |
| part = 学习阶段，顺序即学习顺序 | scope-and-sequence 惯例；UbD WHERETO 序列原则 | ✅ 正统 |
| why = 弱点归因，「归约不进去的课不值得存在」 | 本项目原创（归因对象是模型失能）；结构同构于 UbD 的「不服务考核结果的活动质问其存在」 | ✅ 合理迁移，差异化亮点 |
| scope = 讲什么/不讲什么 | `/teach` MISSION.md 的 Out of scope 字段（保护 ZPD） | ✅ 撞对 |
| 检查点先于正文设计（submit_plan 规划测验→逐节写） | UbD 核心：「考核证据先于教学活动设计；多数人反过来，产生错位」 | ✅ 精确实现 |
| 规划兑现验收（漏节/漏测验打回） | Biggs & Tang 建构性对齐的程序闸版——比 education-agent-skills 的自查版强一档 | ✅ 超出参考实现 |
| 3~8 门 | 已考据（2026-11-17）：教学惯例带 + MOOC 完课率；正确避开 Miller 7±2 误用 | ✅ 有据 |
| 大纲语义审查闸（对照原文快照，failed 拒出课） | 参考库无对应物，最近为 assessment-validity-checker（只查考核不查大纲） | ✅ 独有强项 |

**三条已知差距**（非意外遗漏，记录在案）：①缺贯穿全书的开放问题线（essential questions）；②大纲是静态路线、不吃学员状态（单人系统的正确取舍）；③检查点偏复述、缺迁移——③由 T3 解决。

## 附录 B：调研仓库清单

| 仓库 | star | 一句话 | 对本项目的价值层 |
|---|---|---|---|
| [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master) | 79.6k | 原生可编辑 PPTX 生成，SKILL.md 工程纪律教科书 | prep 循环改造对标范文（不借输出） |
| [GarethManning/education-agent-skills](https://github.com/GarethManning/education-agent-skills) | 1.0k | 165 个教育 skills × 20 域，证据分级+typed schema | T4 渐隐示范；间隔/检索科学背书 |
| [mattpocock/skills 的 /teach](https://github.com/mattpocock/skills/blob/main/skills%2Fproductivity%2Fteach%2FSKILL.md) | — | 有状态教学 workspace（MISSION/学习记录/ZPD） | T2 错因结构化的理论来源；T1 反出千规则 |
| [dair-ai/dair-academy-plugins 的 lesson-generator](https://github.com/dair-ai/dair-academy-plugins/blob/main/plugins/lesson-generator/skills/lesson-generator/SKILL.md) | — | 自包含多课 HTML 课程（objectives/闪卡/quiz/来源卡） | T3 综合复习思想；T1 先例后抽象 |
