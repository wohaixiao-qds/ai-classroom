import type { ReactNode } from "react";

/** 分区标题条(学习台/生成中心共用):emoji + 标题 + 计数 + 一句提示 */
export function Lane({
  emoji,
  title,
  count,
  hint,
  children,
}: {
  emoji: string;
  title: string;
  count: number;
  hint: string;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-3 flex items-baseline gap-2">
        <h2 className="text-lg font-medium">
          {emoji} {title}
        </h2>
        <span className="muted font-mono text-xs">{count}</span>
        <span className="muted text-xs">· {hint}</span>
      </div>
      {children}
    </section>
  );
}
