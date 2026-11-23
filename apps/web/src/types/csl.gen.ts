// Generated from apps/api/app/schemas/csl.py. Run pnpm gen-csl-types.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** CalloutBlock */
        CalloutBlock: {
            /**
             * Evidence Ids
             * @default []
             */
            evidence_ids: string[];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "callout";
            /**
             * Kind
             * @default note
             * @enum {string}
             */
            kind: "tip" | "warn" | "note";
            /** Text */
            text: string;
        };
        /**
         * Checkpoint
         * @description 复述检查点：自学模式下页面讲完自动暂停，学员复述通过才继续。
         */
        Checkpoint: {
            /** Question */
            question: string;
            /**
             * Hint
             * @default null
             */
            hint: string | null;
            /**
             * Pass Rule
             * @default null
             */
            pass_rule: string | null;
        };
        /** CodeBlock */
        CodeBlock: {
            /**
             * Evidence Ids
             * @default []
             */
            evidence_ids: string[];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "code";
            /**
             * Language
             * @default text
             */
            language: string;
            /** Code */
            code: string;
            /**
             * Caption
             * @default null
             */
            caption: string | null;
        };
        /** CodeContent */
        CodeContent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "code";
            /**
             * Language
             * @default python
             */
            language: string;
            /** Lines */
            lines: components["schemas"]["CodeLine"][];
            /**
             * Note
             * @default null
             */
            note: string | null;
        };
        /** CodeLine */
        CodeLine: {
            /** Code */
            code: string;
            /**
             * Comment
             * @default null
             */
            comment: string | null;
            /**
             * Highlight
             * @default null
             */
            highlight: string | null;
        };
        /**
         * Course
         * @description 一份 CSL 课件 = 一个 .csl.json 文件。
         */
        Course: {
            /** Id */
            id: string;
            /** Title */
            title: string;
            /**
             * Scenario
             * @enum {string}
             */
            scenario: "自学" | "复习" | "对外";
            meta: components["schemas"]["CourseMeta"];
            /** Pages */
            pages: components["schemas"]["Page"][];
        };
        /**
         * CourseDep
         * @description 先修依赖(学习顺序):这门课开课之前建议先学完的课。人工/备课 agent 写,
         *     课表「下一步学」与课程库「建议先学」都从这里读;只作展示,不锁进入。
         */
        CourseDep: {
            /** Id */
            id: string;
            /**
             * Reason
             * @default null
             */
            reason: string | null;
        };
        /** CourseMeta */
        CourseMeta: {
            /**
             * Source Notes
             * @default []
             */
            source_notes: string[];
            /**
             * Sources
             * @default []
             */
            sources: components["schemas"]["SourceRef"][];
            /**
             * Publication Required
             * @default false
             */
            publication_required: boolean;
            /** @default null */
            publication_review: components["schemas"]["PublicationReview"] | null;
            /**
             * Evidence
             * @default []
             */
            evidence: components["schemas"]["EvidenceItem"][];
            /**
             * Topic
             * @default null
             */
            topic: string | null;
            /**
             * Depends On
             * @default []
             */
            depends_on: components["schemas"]["CourseDep"][];
            /**
             * Duration Min
             * @default null
             */
            duration_min: number | null;
            /**
             * Version
             * @default 1
             */
            version: number;
        };
        /**
         * CourseV2
         * @description v2 书页课件:滚动文章形态,文字+插图,检查点/闪卡内嵌。
         */
        CourseV2: {
            /** Id */
            id: string;
            /** Title */
            title: string;
            /**
             * Scenario
             * @enum {string}
             */
            scenario: "自学" | "复习" | "对外";
            /**
             * Version
             * @default 2
             * @constant
             */
            version: 2;
            meta: components["schemas"]["CourseMeta"];
            /** Sections */
            sections: components["schemas"]["Section"][];
        };
        /** CoverContent */
        CoverContent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "cover";
            /**
             * Equation
             * @default null
             */
            equation: string | null;
            /**
             * Meta
             * @default []
             */
            meta: [
                string,
                string
            ][];
        };
        /**
         * DiagramBlock
         * @description mermaid 示意图(P6 插图):前端渲染失败降级为代码块。
         */
        DiagramBlock: {
            /**
             * Evidence Ids
             * @default []
             */
            evidence_ids: string[];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "diagram";
            /**
             * Lang
             * @default mermaid
             * @constant
             */
            lang: "mermaid";
            /** Code */
            code: string;
            /**
             * Caption
             * @default null
             */
            caption: string | null;
        };
        /** DiagramContent */
        DiagramContent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "diagram";
            /** Asset */
            asset: string;
            /**
             * Legend
             * @default []
             */
            legend: components["schemas"]["LegendItem"][];
        };
        /** DuoCard */
        DuoCard: {
            /** Title */
            title: string;
            /** Tag */
            tag: string;
            /** Body */
            body: string;
        };
        /** DuoContent */
        DuoContent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "duo";
            left: components["schemas"]["DuoCard"];
            right: components["schemas"]["DuoCard"];
        };
        /**
         * EvidenceItem
         * @description 原料要点及其原文定位。摘录命中和语义支撑是两种独立的检查。
         */
        EvidenceItem: {
            /** Id */
            id: string;
            /** Point */
            point: string;
            /**
             * Source Id
             * @default null
             */
            source_id: number | null;
            /**
             * Quote
             * @default null
             */
            quote: string | null;
            /**
             * Context
             * @default null
             */
            context: string | null;
            /**
             * Source Hash
             * @default null
             */
            source_hash: string | null;
            /**
             * Quote Start
             * @default null
             */
            quote_start: number | null;
            /**
             * Quote End
             * @default null
             */
            quote_end: number | null;
            /**
             * Quote Status
             * @default missing
             * @enum {string}
             */
            quote_status: "matched" | "missing";
            /**
             * Support
             * @default unreviewed
             * @enum {string}
             */
            support: "supported" | "partial" | "unsupported" | "uncertain" | "unreviewed";
            /**
             * Reviewer
             * @default null
             */
            reviewer: string | null;
            /**
             * Reason
             * @default null
             */
            reason: string | null;
        };
        /** Flashcard */
        Flashcard: {
            /** Front */
            front: string;
            /** Back */
            back: string;
        };
        /**
         * FlashcardsBlock
         * @description 闪卡(P5·T5 并入):复习队列的消费单元。
         */
        FlashcardsBlock: {
            /**
             * Evidence Ids
             * @default []
             */
            evidence_ids: string[];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "flashcards";
            /** Cards */
            cards: components["schemas"]["Flashcard"][];
        };
        /** FormulaContent */
        FormulaContent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "formula";
            /** Items */
            items: string[];
            /** Conclusion */
            conclusion: string;
        };
        /**
         * Fragment
         * @description 一个动画步进单元：讲稿第 with_sentence 句**开讲时**触发本动画。
         *
         *     时序原则「讲到什么,亮什么」:元素在提到它的那句话开始时出现,
         *     而不是念完才出现。一句可带多个 fragment(如公式五项一起弹出)。
         */
        Fragment: {
            /**
             * Effect
             * @default fade
             */
            effect: string;
            /**
             * Target
             * @default null
             */
            target: string | null;
            /** With Sentence */
            with_sentence: number;
        };
        /** LegendItem */
        LegendItem: {
            /** Label */
            label: string;
            /** Color */
            color: string;
            /** Note */
            note: string;
        };
        /** Page */
        Page: {
            /** Id */
            id: string;
            /**
             * Eyebrow
             * @default null
             */
            eyebrow: string | null;
            /**
             * Title
             * @default null
             */
            title: string | null;
            /** Content */
            content: components["schemas"]["CoverContent"] | components["schemas"]["FormulaContent"] | components["schemas"]["DiagramContent"] | components["schemas"]["DuoContent"] | components["schemas"]["CodeContent"] | components["schemas"]["TableContent"] | components["schemas"]["QuizContent"];
            /** Script */
            script: components["schemas"]["Sentence"][];
            /**
             * Fragments
             * @default []
             */
            fragments: components["schemas"]["Fragment"][];
            /** @default null */
            checkpoint: components["schemas"]["Checkpoint"] | null;
        };
        /**
         * ParagraphBlock
         * @description 书面 prose 段落;支持 **加粗** 与 `行内代码`。
         */
        ParagraphBlock: {
            /**
             * Evidence Ids
             * @default []
             */
            evidence_ids: string[];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "p";
            /** Text */
            text: string;
        };
        /**
         * PublicationReview
         * @description 摘要只供展示,发布还需验证独立报告与内容指纹。
         */
        PublicationReview: {
            /**
             * Status
             * @enum {string}
             */
            status: "program_passed" | "model_reviewed" | "blocked" | "unreviewed";
            /** Content Hash */
            content_hash: string;
            /** Report Hash */
            report_hash: string;
            /** Reviewed At */
            reviewed_at: string;
            /** Reviewer */
            reviewer: string;
            /**
             * Program Status
             * @default null
             */
            program_status: ("passed" | "blocked") | null;
            /**
             * Model Review Status
             * @default null
             */
            model_review_status: ("completed" | "partial" | "failed" | "not_run") | null;
        };
        /**
         * QuizBlock
         * @description 复述检查点(原 v1 page.checkpoint)或自测题,内嵌节末。
         */
        QuizBlock: {
            /**
             * Evidence Ids
             * @default []
             */
            evidence_ids: string[];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "quiz";
            /** Id */
            id: string;
            /** Question */
            question: string;
            /**
             * Hint
             * @default null
             */
            hint: string | null;
            /**
             * Pass Rule
             * @default null
             */
            pass_rule: string | null;
        };
        /** QuizContent */
        QuizContent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "quiz";
            /** Questions */
            questions: string[];
        };
        /**
         * Section
         * @description 书页的一节:标题 + 有序块列表。一节 ≈ 原 v1 一页的容量。
         */
        Section: {
            /** Id */
            id: string;
            /** Heading */
            heading: string;
            /** Blocks */
            blocks: (components["schemas"]["ParagraphBlock"] | components["schemas"]["DiagramBlock"] | components["schemas"]["CodeBlock"] | components["schemas"]["TableBlock"] | components["schemas"]["CalloutBlock"] | components["schemas"]["QuizBlock"] | components["schemas"]["FlashcardsBlock"])[];
            /** @default null */
            audio: components["schemas"]["SectionAudio"] | null;
        };
        /**
         * SectionAudio
         * @description 段级朗读留位(P6 拍板:TTS 先砍不加,字段位留给未来)。
         */
        SectionAudio: {
            /** Path */
            path: string;
        };
        /**
         * Sentence
         * @description 讲稿中的一句。一句 = 一个 TTS 音频文件 = 一次 fragment 步进。
         */
        Sentence: {
            /** Text */
            text: string;
            /**
             * Audio
             * @default null
             */
            audio: string | null;
        };
        /**
         * SourceRef
         * @description 来源目录;id 保留调研编号,列表位置不能替代来源身份。
         */
        SourceRef: {
            /** Title */
            title: string;
            /** Url */
            url: string;
            /**
             * Id
             * @default null
             */
            id: number | null;
        };
        /** TableBlock */
        TableBlock: {
            /**
             * Evidence Ids
             * @default []
             */
            evidence_ids: string[];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "table";
            /** Header */
            header: string[];
            /** Rows */
            rows: string[][];
            /**
             * Caption
             * @default null
             */
            caption: string | null;
        };
        /** TableContent */
        TableContent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "table";
            /** Headers */
            headers: string[];
            /** Rows */
            rows: string[][];
            /**
             * Note
             * @default null
             */
            note: string | null;
        };
        AnyCourse: components["schemas"]["Course"] | components["schemas"]["CourseV2"];
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export type operations = Record<string, never>;
