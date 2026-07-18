"use client";

import { motion } from "motion/react";
import { cn } from "@/lib/utils";

export type Verdict = "fair" | "mid" | "high";

const CFG: Record<Verdict, { color: string; value: number; ring: string }> = {
  fair: { color: "var(--color-fair)", value: 0.26, ring: "text-fair" },
  mid: { color: "var(--color-mid)", value: 0.58, ring: "text-mid" },
  high: { color: "var(--color-high)", value: 0.86, ring: "text-high" },
};

const R = 80;
const CX = 100;
const CY = 104;
const LEN = Math.PI * R; // semicircle length

function pointAt(t: number) {
  const rad = (Math.PI * (1 - t)); // 180deg -> 0deg
  return { x: CX + R * Math.cos(rad), y: CY - R * Math.sin(rad) };
}

/** Semicircular price gauge, coloured by verdict, with an animated sweep. */
export function Gauge({
  verdict,
  label,
  sublabel,
  className,
}: {
  verdict: Verdict;
  label: string;
  sublabel?: string;
  className?: string;
}) {
  const cfg = CFG[verdict];
  const tip = pointAt(cfg.value);

  return (
    <div className={cn("relative mx-auto w-[240px]", className)}>
      <svg viewBox="0 0 200 128" className="w-full overflow-visible">
        {/* zones on the track */}
        <path
          d={`M20 104 A80 80 0 0 1 180 104`}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth="14"
          strokeLinecap="round"
        />
        {/* coloured progress */}
        <motion.path
          d={`M20 104 A80 80 0 0 1 180 104`}
          fill="none"
          stroke={cfg.color}
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray={LEN}
          initial={{ strokeDashoffset: LEN }}
          animate={{ strokeDashoffset: LEN * (1 - cfg.value) }}
          transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
        />
        {/* indicator dot */}
        <motion.circle
          r="9"
          fill="#fff"
          stroke={cfg.color}
          strokeWidth="5"
          initial={{ cx: pointAt(0).x, cy: pointAt(0).y, opacity: 0 }}
          animate={{ cx: tip.x, cy: tip.y, opacity: 1 }}
          transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
        />
      </svg>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col items-center">
        <span
          className={cn("font-display text-2xl font-extrabold leading-tight", cfg.ring)}
        >
          {label}
        </span>
        {sublabel && (
          <span className="text-xs font-medium text-ink-mute">{sublabel}</span>
        )}
      </div>
    </div>
  );
}
