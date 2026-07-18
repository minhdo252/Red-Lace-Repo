import { type ReactNode } from "react";

/**
 * Minimal, dependency-free markdown renderer for LLM replies (the price advisor
 * and orchestrator emit light markdown). Handles **bold**, *italic*, `- ` / `* `
 * bullet lists, and line breaks. No dangerouslySetInnerHTML — everything is built
 * as React nodes, so the model's `*` markers render as styling, not raw text.
 */

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    if (match[1] !== undefined) {
      nodes.push(
        <strong key={`${keyPrefix}-b${i}`} className="font-bold">
          {match[1]}
        </strong>,
      );
    } else if (match[2] !== undefined) {
      nodes.push(<em key={`${keyPrefix}-i${i}`}>{match[2]}</em>);
    }
    last = match.index + match[0].length;
    i += 1;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = (text ?? "").split("\n");
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = (key: string) => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={key} className="my-1.5 list-disc space-y-1 pl-5">
        {items.map((b, i) => (
          <li key={i}>{renderInline(b, `${key}-${i}`)}</li>
        ))}
      </ul>,
    );
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();
    const bullet = trimmed.match(/^[-*]\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
      return;
    }
    flushBullets(`ul-${idx}`);
    if (trimmed === "") return; // collapse blank lines between paragraphs
    blocks.push(
      <p key={`p-${idx}`} className="[&:not(:first-child)]:mt-2">
        {renderInline(line, `p-${idx}`)}
      </p>,
    );
  });
  flushBullets("ul-end");

  return <div className={className}>{blocks}</div>;
}
