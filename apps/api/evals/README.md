# 离线 Agent 评测

这组用例用于变更前后固定输入、比较真实输出。覆盖答疑(有据/未知/复述引导/笔记衔接)、调研(先修 DAG/来源)、备课(v2/测验)和批改(弱答案/辅导保底)。不调用收费模型、不运行备课发布、不写学习记录或知识库。

`cases.json` 的每条包含 `input`、可机械检查的 `expect`、人工语义评分项 `rubric`、参考输出和反例。参考输出只验证检查器本身，不能作为当前模型成绩。它们不是充分的事实基准；特别是来源忠实度、教学质量需要审阅原文并标注。

在 `apps/api` 下执行：

```bash
.venv/bin/python scripts/eval_agent.py --self-check
.venv/bin/python scripts/eval_agent.py --outputs /tmp/candidate.jsonl > /tmp/eval-report.json
```

第一条验证参考输出通过且反例被拒绝。第二条检查指定的实际输出，缺任何用例、版本或输入哈希都会失败。每行格式：

```json
{"case_id":"tutor-known","output":{"answer":"...","tool_calls":[]},"versions":{"model":"实际模型版本","prompt_hash":"实际使用提示的SHA256","context_hash":"实际模型上下文的SHA256","code_hash":"执行代码的SHA256","input_hash":"固定用例input的SHA256"}}
```

所有哈希使用 `app.core.trace.digest`：UTF-8、JSON 键排序后 SHA256。新执行的版本与实际初始上下文保存在 `traces/*.jsonl` 和 `data/eval-context/<run_id>.json`；这些文件只供本地复盘，不进入 Git。采集候选时须让模型使用固定用例给出的材料、历史、进度和工具返回，避免混入个人学习状态；当前入口只评已有输出，不负责自动调用生产循环。未固定的额外上下文要如实记录，不能作为同条件回归比较。

报告提供 `review_template`。审阅输入、来源及输出后，将评分项填为布尔值，并把具名 `reviewer`、`checks` 和对应 `output_hash` 放入该行的 `human_review` 后重跑。更改输出后旧标签因哈希不符失效。模型自评不能充当人工标签。

退出码：`0` = 所有规则与人工评分通过；`1` = 缺输出/规则失败/人工判失败/输入格式错误；`2` = 规则通过但仍缺人工评分。报告分别给规则成绩、人工语义成绩、未评数。`--self-check` 成功不表示已经跑过真实模型。

当前局限：9 个种子用例不足以代表实际问题分布；短语检查只检验明确约束，不等于语义正确；线上裁判与答疑共用模型，尚无足够人工标签校准其误判率。应持续把真实失败转成固定用例，并在更换模型/prompt 时保留候选输出与人工评分。
