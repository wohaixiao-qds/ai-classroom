/** 生成中心：新建主题 → 生成任务 → 领域大纲 → 折叠待学清单。 */
import { LoaderCircle, Sprout, SquarePen } from "lucide-react";
import { useRef, useState } from "react";

import { PageError, PageLoading } from "../../components/PageState";
import { SectionHeader } from "../../components/SectionHeader";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useCatalog } from "../../hooks/useCatalog";
import type { components } from "../../types/api.gen";
import { GenerationTasks } from "./GenerationTasks";
import { NotePicker } from "./NotePicker";
import { OutlinePanel } from "./OutlinePanel";
import { studioRequest } from "./studioRequest";
import type { StudioJobFocus } from "./studioRequest";
import { WishlistPanel } from "./WishlistPanel";

export function StudioPage() {
  const { cat, err } = useCatalog();
  const [topic, setTopic] = useState("");
  const [requestState, setRequestState] = useState<"idle" | "pending" | "accepted" | "saved" | "failed">("idle");
  const [requestAction, setRequestAction] = useState<"generate" | "save">("generate");
  const [requestError, setRequestError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [wishlistRevision, setWishlistRevision] = useState(0);
  const [notePickerOpen, setNotePickerOpen] = useState(false);
  const [focusJob, setFocusJob] = useState<StudioJobFocus | null>(null);
  const submitting = useRef(false);
  const noteTrigger = useRef<HTMLButtonElement>(null);

  async function submit(action: "generate" | "save") {
    const title = topic.trim();
    if (!title || submitting.current) return;
    submitting.current = true;
    setRequestState("pending");
    setRequestAction(action);
    setRequestError("");
    try {
      if (action === "save") {
        const body: components["schemas"]["WishlistSave"] = { title };
        const saved = await studioRequest<components["schemas"]["WishlistItem"]>("/api/v1/wishlist", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        setSaveNotice(saved.job ? "已保存到待学清单；该主题已有任务记录，本次未启动生成。" : "已保存到待学清单，尚未开始生成。");
        setWishlistRevision((value) => value + 1);
        setRequestState("saved");
      } else {
        const body: components["schemas"]["CatalogAction"] = { kind: "request_research", target: title, label: title };
        await studioRequest<components["schemas"]["ActionResult"]>("/api/v1/catalog/action", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        setFocusJob({ kind: "request_research", target: title });
        setRequestState("accepted");
      }
      setTopic("");
    } catch (cause: unknown) {
      setRequestState("failed");
      setRequestError(cause instanceof Error ? cause.message : "操作失败，主题已保留，请重试。");
    } finally {
      submitting.current = false;
    }
  }

  if (err && !cat) return <PageError message={`加载失败:${err}`} />;
  if (!cat) return <PageLoading />;

  return (
    <div className="workspace-page space-y-8">
      <header className="workspace-header">
        <div>
          <h1 className="workspace-title">生成中心</h1>
          <p className="workspace-description">输入想学的主题，查看生成流程与可核查依据，再按大纲逐课学习。</p>
        </div>
      </header>

      <section className="rounded-2xl border border-border bg-card p-4 shadow-(--shadow-1) sm:p-6">
        <SectionHeader icon={Sprout} title="新建学习主题" hint="开始生成后，先调研学习路线，再生成领域大纲与第一门样课。" />
        <form onSubmit={(event) => { event.preventDefault(); void submit("generate"); }} className="mt-4 flex max-w-3xl flex-wrap gap-2">
          <Input
            aria-label="想学的主题"
            value={topic}
            readOnly={requestState === "pending"}
            onChange={(event) => { setTopic(event.target.value); setRequestState("idle"); setRequestError(""); }}
            placeholder="想学什么？例如 MCP、RAG 或编译原理"
            className="min-h-11 min-w-0 flex-[1_1_16rem]"
          />
          <Button type="submit" className="min-h-11 lg:min-w-32" disabled={!topic.trim() || requestState === "pending"}>
            {requestState === "pending" && requestAction === "generate" && <span className="desktop-state-arrive inline-flex"><LoaderCircle aria-hidden="true" className="motion-safe:animate-spin" /></span>}
            {requestState === "pending" && requestAction === "generate" ? "提交中…" : "开始生成"}
          </Button>
          <Button type="button" variant="outline" className="min-h-11" disabled={!topic.trim() || requestState === "pending"} onClick={() => void submit("save")}>
            {requestState === "pending" && requestAction === "save" ? "保存中…" : "先存起来"}
          </Button>
        </form>
        <p role="status" className="text-sm text-primary">
          {requestState === "pending" && <span className="sr-only">{requestAction === "generate" ? "正在提交生成请求。" : "正在保存主题。"}</span>}
          {requestState === "accepted" && <span className="anim-drop mt-3 inline-block">已提交生成请求，对应任务已展开，可查看节点进度。</span>}
          {requestState === "saved" && <span className="anim-drop mt-3 inline-block">{saveNotice}</span>}
        </p>
        <p role="alert" className="text-sm text-destructive">
          {requestState === "failed" && <span className="mt-3 inline-block break-words">{requestError}</span>}
          {err && requestState !== "failed" && requestState !== "pending" && <span className="mt-3 inline-block">{err}</span>}
        </p>
        <Button ref={noteTrigger} variant="ghost" className="mt-3 min-h-11 text-muted-foreground" onClick={() => setNotePickerOpen(true)}><SquarePen size={16} aria-hidden="true" />从已有笔记生成</Button>
      </section>

      <GenerationTasks refreshKey={requestState} focusJob={focusJob} />
      <OutlinePanel />
      <WishlistPanel refreshKey={wishlistRevision} onFocusJob={(job) => setFocusJob({ ...job })} />
      {notePickerOpen && <NotePicker open onOpenChange={setNotePickerOpen} notes={cat.notes} returnFocus={() => noteTrigger.current?.focus()} onFocusJob={(job) => setFocusJob({ ...job })} />}
    </div>
  );
}
