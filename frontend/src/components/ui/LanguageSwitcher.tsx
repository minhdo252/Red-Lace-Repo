"use client";

import { useState } from "react";
import { Check, ChevronDown, Languages } from "lucide-react";
import { LOCALES, useApp } from "@/i18n";
import { BottomSheet } from "./BottomSheet";
import { cn } from "@/lib/utils";

export function LanguageSwitcher({
  compact = false,
  tone = "light",
}: {
  compact?: boolean;
  tone?: "light" | "dark";
}) {
  const { locale, setLocale } = useApp();
  const [open, setOpen] = useState(false);
  const current = LOCALES.find((l) => l.code === locale)!;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full font-semibold transition-colors",
          compact ? "px-2.5 py-1.5 text-sm" : "px-3.5 py-2 text-sm",
          tone === "dark"
            ? "bg-white/12 text-white hover:bg-white/20"
            : "bg-surface text-ink shadow-[var(--shadow-soft)]",
        )}
      >
        {compact ? (
          <Languages size={16} />
        ) : (
          <span className="grid h-5 min-w-6 place-items-center rounded bg-moss-soft px-1 text-[0.6rem] font-extrabold text-forest">
            {current.code.toUpperCase()}
          </span>
        )}
        <span>{compact ? current.code.toUpperCase() : current.label}</span>
        <ChevronDown size={15} className="opacity-60" />
      </button>

      <BottomSheet open={open} onClose={() => setOpen(false)}>
        <h3 className="mb-1 font-display text-lg font-bold text-ink">Language</h3>
        <p className="mb-4 text-sm text-ink-mute">The whole app follows your choice.</p>
        <div className="space-y-1.5">
          {LOCALES.map((l) => {
            const active = l.code === locale;
            return (
              <button
                key={l.code}
                onClick={() => {
                  setLocale(l.code);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center gap-3 rounded-2xl px-3.5 py-3 text-left transition-colors",
                  active ? "bg-moss-soft" : "hover:bg-surface-2",
                )}
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-moss-soft text-[0.72rem] font-extrabold text-forest">
                  {l.code.toUpperCase()}
                </span>
                <span className="flex-1">
                  <span className={cn("block font-semibold", active ? "text-forest" : "text-ink")}>{l.label}</span>
                  <span className={cn("block text-xs", active ? "text-forest/70" : "text-ink-mute")}>{l.english}</span>
                </span>
                {active && (
                  <span className="grid h-6 w-6 place-items-center rounded-full bg-moss text-white">
                    <Check size={14} strokeWidth={3} />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </BottomSheet>
    </>
  );
}
