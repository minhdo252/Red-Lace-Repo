"use client";

import { ShieldAlert, Receipt } from "lucide-react";
import { cn } from "@/lib/utils";
import { summary } from "@/mocks/translate";

type SummaryData = {
  topic: string;
  pricesHeard: { label: string; value: string; tone: "high" | "mid" | "fair" }[];
  scamCount: number;
  /** Unusually-high prices flagged (a caution, counted apart from real scams). */
  priceCount?: number;
};

export function TranscriptSummary({
  title,
  priceLabel,
  scamFlaggedLabel = "Possible scam flagged",
  priceFlaggedLabel = "Price flagged — higher than usual",
  data,
}: {
  title: string;
  priceLabel: string;
  /** Localized chip labels (fall back to English for the mock/demo path). */
  scamFlaggedLabel?: string;
  priceFlaggedLabel?: string;
  /** Real summary from the backend; falls back to the mock summary when absent. */
  data?: SummaryData;
}) {
  const s: SummaryData = data ?? summary;
  return (
    <div className="rounded-2xl bg-surface p-4 shadow-[var(--shadow-soft)]">
      <p className="font-display text-sm font-bold text-ink">{title}</p>
      <p className="mt-0.5 text-sm text-ink-soft">{s.topic}</p>

      <div className="mt-3 flex items-center gap-1.5 text-xs font-semibold text-ink-mute">
        <Receipt size={13} /> {priceLabel}
      </div>
      <div className="mt-2 space-y-1.5">
        {s.pricesHeard.map((p) => (
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

      {s.scamCount > 0 && (
        <div className="mt-3 flex items-center gap-2 rounded-xl bg-danger/12 px-3 py-2 text-sm font-semibold text-danger">
          <ShieldAlert size={15} />
          {scamFlaggedLabel}
        </div>
      )}

      {(s.priceCount ?? 0) > 0 && (
        <div className="mt-3 flex items-center gap-2 rounded-xl bg-mid/15 px-3 py-2 text-sm font-semibold text-mid">
          <Receipt size={15} />
          {priceFlaggedLabel}
        </div>
      )}
    </div>
  );
}
