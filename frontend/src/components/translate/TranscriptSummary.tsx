"use client";

import { ShieldAlert, Receipt } from "lucide-react";
import { cn } from "@/lib/utils";
import { summary } from "@/mocks/translate";

export function TranscriptSummary({
  title,
  priceLabel,
}: {
  title: string;
  priceLabel: string;
}) {
  return (
    <div className="rounded-2xl bg-surface p-4 shadow-[var(--shadow-soft)]">
      <p className="font-display text-sm font-bold text-ink">{title}</p>
      <p className="mt-0.5 text-sm text-ink-soft">{summary.topic}</p>

      <div className="mt-3 flex items-center gap-1.5 text-xs font-semibold text-ink-mute">
        <Receipt size={13} /> {priceLabel}
      </div>
      <div className="mt-2 space-y-1.5">
        {summary.pricesHeard.map((p) => (
          <div key={p.label} className="flex items-center justify-between text-sm">
            <span className="text-ink-soft">{p.label}</span>
            <span
              className={cn(
                "font-semibold",
                p.tone === "high" && "text-high",
                p.tone === "mid" && "text-mid",
                p.tone === "fair" && "text-fair",
              )}
            >
              {p.value}
            </span>
          </div>
        ))}
      </div>

      {summary.scamCount > 0 && (
        <div className="mt-3 flex items-center gap-2 rounded-xl bg-danger/12 px-3 py-2 text-sm font-semibold text-danger">
          <ShieldAlert size={15} />
          {summary.scamCount} scam pattern flagged
        </div>
      )}
    </div>
  );
}
