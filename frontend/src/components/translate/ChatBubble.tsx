"use client";

import { motion } from "motion/react";
import { cn } from "@/lib/utils";
import type { TranslateTurn } from "@/mocks/types";

/**
 * A bilingual bubble. English (what the tourist reads) is primary;
 * Vietnamese (what the vendor reads) is the muted secondary line.
 */
export function ChatBubble({
  turn,
  youLabel,
  themLabel,
}: {
  turn: TranslateTurn;
  youLabel: string;
  themLabel: string;
}) {
  const mine = turn.speaker === "you";
  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className={cn("flex flex-col", mine ? "items-end" : "items-start")}
    >
      <span className="mb-1 px-1 text-[0.7rem] font-semibold uppercase tracking-wide text-ink-mute">
        {mine ? youLabel : themLabel}
      </span>
      <div
        className={cn(
          "max-w-[84%] rounded-2xl px-4 py-3",
          mine
            ? "rounded-br-md bg-teal-deep text-white"
            : "rounded-bl-md bg-surface text-ink shadow-[var(--shadow-soft)]",
          turn.scam && (turn.scam.kind === "price" ? "ring-2 ring-mid/55" : "ring-2 ring-danger/60"),
        )}
      >
        <p className="text-[0.95rem] font-medium leading-snug">{turn.en}</p>
        <p
          className={cn(
            "mt-1.5 border-t pt-1.5 text-[0.82rem] leading-snug",
            mine ? "border-white/25 text-white/85" : "border-line text-ink-soft",
          )}
        >
          {turn.vi}
        </p>
      </div>
    </motion.div>
  );
}
