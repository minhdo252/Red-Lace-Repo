"use client";

import { motion } from "motion/react";
import { ShieldAlert, ShieldQuestion } from "lucide-react";
import { cn } from "@/lib/utils";

/** Slide-in warning the AI shows on a flagged turn. Theme-aware. `tone` picks the
 * severity: "danger" (red) for a real scam pattern, "caution" (amber) for an
 * unusually-high price — the same soft framing the chatbot uses. */
export function ScamBanner({
  title,
  pattern,
  advice,
  actionLabel,
  tone = "danger",
}: {
  title: string;
  pattern?: string;
  advice: string;
  actionLabel?: string;
  tone?: "danger" | "caution";
}) {
  const danger = tone === "danger";
  const Icon = danger ? ShieldAlert : ShieldQuestion;
  return (
    <motion.div
      initial={{ opacity: 0, y: -14, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", damping: 22, stiffness: 300 }}
      className={cn(
        "overflow-hidden rounded-2xl border",
        danger ? "border-danger/35 bg-danger/10" : "border-mid/45 bg-mid/12",
      )}
    >
      <div className="flex items-start gap-3 p-4">
        <motion.span
          className={cn(
            "grid h-10 w-10 shrink-0 place-items-center rounded-xl text-white",
            danger ? "bg-danger" : "bg-mid",
          )}
          animate={{ rotate: [0, -8, 8, -6, 0] }}
          transition={{ duration: 0.6, delay: 0.2 }}
        >
          <Icon size={20} />
        </motion.span>
        <div className="min-w-0 flex-1">
          <p className="font-display font-bold text-ink">{title}</p>
          {pattern && (
            <p className={cn("mt-0.5 text-[0.82rem] font-semibold", danger ? "text-danger" : "text-mid")}>
              {pattern}
            </p>
          )}
          <p className="mt-1.5 text-[0.85rem] leading-snug text-ink-soft text-pretty">{advice}</p>
        </div>
      </div>
      {actionLabel && (
        <button className="w-full border-t border-line bg-surface py-3 text-sm font-semibold text-ink active:bg-surface-2">
          {actionLabel}
        </button>
      )}
    </motion.div>
  );
}
