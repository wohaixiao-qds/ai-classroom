/* oxlint-disable react/only-export-components -- 共享工具(返回 JSX 的纯函数),非组件文件,fast-refresh 规则误伤 */
/** 裸 URL → 可点链接(共享:答疑消息区 + 课件正文块)。
 *  字符集排除 CJK 与全角标点(「详情见 https://a.b/x。」止于 x,中文不粘进链接);
 *  尾部 ASCII 右括号仅不成对时修剪(Wikipedia 路径括号合法)。 */
import type { ReactNode } from "react";

export const URL_RE = /https?:\/\/[^\s<>`"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+/gi;

export function linkifyUrls(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(URL_RE)) {
    let url = m[0];
    while (/[.,;:!?]$/.test(url)) url = url.slice(0, -1);
    const opens = (url.match(/\(/g) ?? []).length;
    const closes = (url.match(/\)/g) ?? []).length;
    while (closes > opens && url.endsWith(")")) url = url.slice(0, -1);
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(
      <a
        key={`${keyBase}-u${i}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        title={url}
        className="break-all text-primary underline decoration-dotted underline-offset-2 hover:decoration-solid"
      >
        {url}
      </a>,
    );
    last = m.index + url.length;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
