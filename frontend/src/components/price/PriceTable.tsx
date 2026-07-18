"use client";

import { motion } from "motion/react";
import { cn, formatVnd } from "@/lib/utils";
import type { PriceItem, Verdict } from "@/mocks/types";

const dot: Record<Verdict, string> = {
  fair: "bg-fair",
  mid: "bg-mid",
  high: "bg-high",
};
const tag: Record<Verdict, { label: string; cls: string }> = {
  fair: { label: "Fair", cls: "text-fair" },
  mid: { label: "High-ish", cls: "text-[oklch(0.55_0.12_70)]" },
  high: { label: "Over", cls: "text-high" },
};

export function PriceTable({ items }: { items: PriceItem[] }) {
  return (
    <div className="overflow-hidden rounded-[var(--radius-card)] bg-surface shadow-[var(--shadow-soft)]">
      {items.map((it, i) => (
        <motion.div
          key={it.name}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 + i * 0.08 }}
          className={cn("flex items-center gap-3 p-3.5", i > 0 && "border-t border-line")}
        >
          <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", dot[it.verdict])} />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold text-ink">
              {it.name} {it.qty > 1 && <span className="text-ink-mute">×{it.qty}</span>}
            </p>
            <p className="text-xs text-ink-mute">
              Usual {formatVnd(it.refLow)}–{formatVnd(it.refHigh)}
            </p>
          </div>
          <div className="text-right">
            <p className="font-display font-bold text-ink">{formatVnd(it.paid)}</p>
            <p className={cn("text-xs font-semibold", tag[it.verdict].cls)}>
              {tag[it.verdict].label}
            </p>
          </div>
        </motion.div>
      ))}
    </div>
  );
}
