"use client";

import { motion } from "motion/react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/** Full-bleed analysing state with a live progress ring and stepping labels. */
export function AnalysisLoader({
  title,
  steps,
  activeIndex,
  percent,
  tone = "moss",
}: {
  title: string;
  steps: string[];
  activeIndex: number;
  percent: number;
  tone?: "moss" | "teal";
}) {
  const stroke = tone === "teal" ? "var(--color-teal)" : "var(--color-moss)";
  const C = 2 * Math.PI * 52;

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-10">
      <div className="relative h-36 w-36">
        <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
          <circle cx="60" cy="60" r="52" fill="none" stroke="var(--color-line)" strokeWidth="8" />
          <motion.circle
            cx="60"
            cy="60"
            r="52"
            fill="none"
            stroke={stroke}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={C}
            animate={{ strokeDashoffset: C * (1 - percent / 100) }}
            transition={{ ease: "linear", duration: 0.2 }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-display text-3xl font-extrabold text-ink">
            {Math.round(percent)}
            <span className="text-lg text-ink-mute">%</span>
          </span>
        </div>
        <span
          className="absolute inset-0 -z-10 m-auto h-24 w-24 rounded-full blur-2xl"
          style={{ background: stroke, opacity: 0.18 }}
        />
      </div>

      <h2 className="mt-7 font-display text-lg font-bold text-ink">{title}</h2>

      <ul className="mt-5 w-full max-w-[280px] space-y-2.5">
        {steps.map((s, i) => {
          const done = i < activeIndex;
          const active = i === activeIndex;
          return (
            <li key={s} className="flex items-center gap-3">
              <span
                className={cn(
                  "grid h-6 w-6 shrink-0 place-items-center rounded-full text-white transition-colors",
                  done && "bg-moss",
                  active && "bg-ink/80",
                  !done && !active && "bg-line",
                )}
              >
                {done ? (
                  <Check size={13} strokeWidth={3} />
                ) : (
                  <span className={cn("h-1.5 w-1.5 rounded-full", active ? "bg-white animate-pulse" : "bg-ink-mute/50")} />
                )}
              </span>
              <span
                className={cn(
                  "text-sm transition-colors",
                  active ? "font-semibold text-ink" : "text-ink-mute",
                )}
              >
                {s}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
