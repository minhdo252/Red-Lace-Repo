"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { PhoneOff, Mic, Volume2, Sparkles, Ambulance } from "lucide-react";
import { useT } from "@/i18n";
import { useTimer, useStaggeredReveal } from "@/lib/hooks";
import { formatDuration } from "@/lib/utils";
import { callScript } from "@/mocks/emergency";
import { cn } from "@/lib/utils";

export default function CallPage() {
  const t = useT("sos");
  const router = useRouter();
  const [connected, setConnected] = useState(false);
  const { seconds } = useTimer(connected);

  useEffect(() => {
    const id = setTimeout(() => setConnected(true), 1600);
    return () => clearTimeout(id);
  }, []);

  const lines = useStaggeredReveal(callScript, connected, 2000);

  return (
    <div
      data-theme="dark"
      className="relative flex h-full flex-col bg-[radial-gradient(130%_100%_at_50%_-10%,#20463c_0%,#14302a_45%,#0e211c_100%)] text-white"
    >
      {/* call header */}
      <header className="flex flex-col items-center gap-1 px-5 pt-[max(env(safe-area-inset-top),1.25rem)]">
        <span className="grid h-16 w-16 place-items-center rounded-full bg-danger/90 shadow-[0_10px_30px_-8px_var(--color-danger)]">
          <Ambulance size={30} />
        </span>
        <h1 className="mt-2 font-display text-xl font-bold">Ambulance · 115</h1>
        <p className="font-mono text-sm text-white/60">
          {connected ? formatDuration(seconds) : t.connecting}
        </p>
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-teal/15 px-3 py-1 text-xs font-semibold text-teal">
          <Sparkles size={13} />
          {t.interpreterOn}
        </div>
      </header>

      {/* interpreted transcript */}
      <div className="scroll-area no-scrollbar mt-4 flex-1 space-y-4 overflow-y-auto px-5">
        {lines.map((line, i) => {
          const mine = line.speaker === "you";
          return (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
              className={cn("flex flex-col", mine ? "items-end" : "items-start")}
            >
              <span className="mb-1 px-1 text-[0.66rem] font-semibold uppercase tracking-wide text-white/40">
                {mine ? "You" : "Operator"}
              </span>
              <div
                className={cn(
                  "max-w-[86%] rounded-2xl px-4 py-3",
                  mine ? "rounded-br-md bg-teal-deep" : "rounded-bl-md bg-white/10 backdrop-blur-sm",
                )}
              >
                <p className="text-[0.95rem] font-medium leading-snug">
                  {mine ? line.en : line.vi}
                </p>
                <div className="mt-1.5 flex items-start gap-1.5 border-t border-white/15 pt-1.5">
                  <Sparkles size={12} className="mt-0.5 shrink-0 text-teal" />
                  <p className="text-[0.82rem] leading-snug text-white/70">
                    {mine ? line.vi : line.en}
                  </p>
                </div>
              </div>
            </motion.div>
          );
        })}
        {connected && lines.length < callScript.length && (
          <div className="flex items-center gap-2 text-sm text-white/45">
            <Sparkles size={13} className="text-teal" /> Nón is interpreting…
          </div>
        )}
        <div className="h-2" />
      </div>

      {/* controls */}
      <div className="shrink-0 px-8 pb-[max(env(safe-area-inset-bottom),1.5rem)] pt-3">
        <div className="flex items-center justify-center gap-8">
          <button className="grid h-14 w-14 place-items-center rounded-full bg-white/10 active:scale-95">
            <Mic size={22} />
          </button>
          <button
            onClick={() => router.push("/sos")}
            aria-label="End call"
            className="grid h-16 w-16 place-items-center rounded-full bg-danger text-white shadow-[0_12px_28px_-8px_var(--color-danger)] active:scale-95"
          >
            <PhoneOff size={26} />
          </button>
          <button className="grid h-14 w-14 place-items-center rounded-full bg-white/10 active:scale-95">
            <Volume2 size={22} />
          </button>
        </div>
      </div>
    </div>
  );
}
