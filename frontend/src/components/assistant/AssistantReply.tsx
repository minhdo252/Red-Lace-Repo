"use client";

import { motion } from "motion/react";
import {
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Car,
  Languages,
  Siren,
  MapPin,
  ReceiptText,
  Link2,
  Camera,
  ArrowRight,
} from "lucide-react";
import type { AssistantMessage, AssistantAction, AssistantVerdict } from "@/mocks/assistant";
import { Markdown } from "@/components/ui/Markdown";
import { cn } from "@/lib/utils";

const verdictCfg: Record<
  AssistantVerdict,
  { label: string; icon: typeof ShieldAlert; bg: string; text: string }
> = {
  safe: { label: "Looks safe", icon: ShieldCheck, bg: "bg-fair/12", text: "text-fair" },
  caution: {
    label: "Be careful",
    icon: ShieldQuestion,
    bg: "bg-mid/18",
    text: "text-[oklch(0.5_0.12_70)]",
  },
  scam: { label: "Likely a scam", icon: ShieldAlert, bg: "bg-danger/12", text: "text-danger" },
};

const actionIcon = {
  grab: Car,
  police: Siren,
  translate: Languages,
  price: ReceiptText,
  tour: Link2,
  map: MapPin,
  retake: Camera,
} as const;

/** The AI's reasoned answer — verdict, why, and what to do. Light (Gemini) surface. */
export function AssistantReply({
  msg,
  doThisLabel,
  onAction,
}: {
  msg: AssistantMessage;
  doThisLabel: string;
  onAction?: (a: AssistantAction) => void;
}) {
  const v = msg.verdict ? verdictCfg[msg.verdict] : null;
  const verdictLabel = msg.verdictLabel ?? v?.label;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className="max-w-[92%]"
    >
      {v && (
        <div className={cn("mb-2.5 inline-flex items-center gap-2 rounded-full px-3 py-1.5", v.bg)}>
          <v.icon size={15} className={v.text} />
          <span className={cn("text-sm font-bold", v.text)}>{verdictLabel}</span>
        </div>
      )}

      <Markdown text={msg.text} className="text-[0.95rem] leading-relaxed text-ink text-pretty" />

      {msg.pattern && (
        <p className="mt-2 text-sm font-semibold text-danger">{msg.pattern}</p>
      )}

      {msg.reasons && (
        <ul className="mt-3 space-y-2">
          {msg.reasons.map((r, i) => (
            <motion.li
              key={i}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 + i * 0.12 }}
              className="flex gap-2.5 text-[0.88rem] leading-snug text-ink-soft"
            >
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-deep" />
              {r}
            </motion.li>
          ))}
        </ul>
      )}

      {msg.actions && (
        <div className="mt-4">
          <p className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wide text-ink-mute">
            {doThisLabel}
          </p>
          <div className="flex flex-wrap gap-2">
            {msg.actions.map((a) => {
              const Icon = actionIcon[a.kind];
              const danger = a.kind === "police";
              return (
                <button
                  key={a.label}
                  onClick={() => onAction?.(a)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-sm font-semibold transition-transform active:scale-95",
                    danger
                      ? "bg-danger text-white"
                      : "bg-surface text-ink shadow-[var(--shadow-soft)] hover:bg-surface-2",
                  )}
                >
                  <Icon size={15} />
                  {a.label}
                  <ArrowRight size={13} className="opacity-50" />
                </button>
              );
            })}
          </div>
        </div>
      )}
    </motion.div>
  );
}
