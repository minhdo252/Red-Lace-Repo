"use client";

import { motion } from "motion/react";
import { ShieldAlert } from "lucide-react";

/** Slide-in warning when the AI detects a scam pattern. Theme-aware. */
export function ScamBanner({
  title,
  pattern,
  advice,
  actionLabel,
}: {
  title: string;
  pattern: string;
  advice: string;
  actionLabel?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -14, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", damping: 22, stiffness: 300 }}
      className="overflow-hidden rounded-2xl border border-danger/35 bg-danger/10"
    >
      <div className="flex items-start gap-3 p-4">
        <motion.span
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-danger text-white"
          animate={{ rotate: [0, -8, 8, -6, 0] }}
          transition={{ duration: 0.6, delay: 0.2 }}
        >
          <ShieldAlert size={20} />
        </motion.span>
        <div className="min-w-0 flex-1">
          <p className="font-display font-bold text-ink">{title}</p>
          <p className="mt-0.5 text-[0.82rem] font-semibold text-danger">{pattern}</p>
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
