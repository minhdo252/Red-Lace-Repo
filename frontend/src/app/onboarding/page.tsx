"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronLeft, Apple, Globe, ArrowRight, ShieldCheck } from "lucide-react";
import { Mascot } from "@/components/ui/Mascot";
import { Button } from "@/components/ui/Button";
import { LOCALES, useApp, useT } from "@/i18n";
import { cn } from "@/lib/utils";

export default function OnboardingPage() {
  const router = useRouter();
  const t = useT("onboarding");
  const common = useT("common");
  const { locale, setLocale } = useApp();
  const [step, setStep] = useState(0);

  const next = () => (step < 1 ? setStep(step + 1) : router.push("/home"));
  const back = () => (step > 0 ? setStep(step - 1) : router.push("/"));

  return (
    <div className="grain relative flex h-full flex-col overflow-hidden bg-[radial-gradient(120%_100%_at_50%_0%,#f1f6ef_0%,#e2ece0_60%,#d3e2cf_100%)]">
      {/* top bar */}
      <div className="flex items-center gap-3 px-5 pb-2 pt-[max(env(safe-area-inset-top),1rem)]">
        <button
          onClick={back}
          aria-label="Back"
          className="grid h-10 w-10 place-items-center rounded-full bg-white/70 text-ink active:scale-95"
        >
          <ChevronLeft size={22} />
        </button>
        <div className="flex flex-1 items-center gap-1.5">
          {[0, 1].map((i) => (
            <span
              key={i}
              className={cn(
                "h-1.5 rounded-full transition-all",
                i === step ? "w-6 bg-moss" : i < step ? "w-4 bg-moss/50" : "w-4 bg-line-strong",
              )}
            />
          ))}
        </div>
      </div>

      <div className="scroll-area no-scrollbar flex-1 overflow-y-auto px-5">
        <AnimatePresence mode="wait">
          {step === 0 && (
            <Step key="lang">
              <Mascot variant="face" size={72} ring className="mb-4" />
              <Heading title={t.chooseLanguage} sub={t.chooseLanguageSub} />
              <div className="mt-5 space-y-2">
                {LOCALES.map((l) => {
                  const active = l.code === locale;
                  return (
                    <button
                      key={l.code}
                      onClick={() => setLocale(l.code)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-2xl border-2 bg-surface px-4 py-3.5 text-left transition-all active:scale-[0.99]",
                        active ? "border-moss shadow-[var(--shadow-soft)]" : "border-transparent",
                      )}
                    >
                      <span className="text-2xl">{l.flag}</span>
                      <span className="flex-1">
                        <span className="block font-semibold text-ink">{l.label}</span>
                        <span className="block text-xs text-ink-mute">{l.english}</span>
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
            </Step>
          )}

          {step === 1 && (
            <Step key="ready">
              <Mascot variant="full" size={150} float className="mb-2" />
              <Heading title={t.login} sub={t.loginSub} />
              <div className="mt-6 w-full space-y-3">
                <Button variant="secondary" block size="lg" onClick={next}>
                  <Globe size={18} /> {t.continueGoogle}
                </Button>
                <Button variant="secondary" block size="lg" onClick={next}>
                  <Apple size={18} /> {t.continueApple}
                </Button>
              </div>
              <p className="mt-4 flex max-w-[32ch] items-start gap-2 text-left text-xs leading-snug text-ink-mute">
                <ShieldCheck size={15} className="mt-0.5 shrink-0 text-moss-strong" />
                {t.accountNote}
              </p>
            </Step>
          )}
        </AnimatePresence>
      </div>

      {/* footer CTA */}
      <div className="shrink-0 px-5 pb-[max(env(safe-area-inset-bottom),1.25rem)] pt-3">
        <Button block size="lg" onClick={next}>
          {step === 1 ? t.start : common.continue}
          <ArrowRight size={18} />
        </Button>
        {step === 1 && (
          <button
            onClick={() => router.push("/home")}
            className="mt-2 w-full py-2 text-sm font-semibold text-ink-mute active:opacity-60"
          >
            {t.guest}
          </button>
        )}
      </div>
    </div>
  );
}

function Step({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col items-center pt-4 text-center"
    >
      {children}
    </motion.div>
  );
}

function Heading({ title, sub }: { title: string; sub: string }) {
  return (
    <>
      <h1 className="font-display text-2xl font-extrabold leading-tight text-ink text-balance">
        {title}
      </h1>
      <p className="mt-1.5 max-w-[30ch] text-[0.9rem] text-ink-soft text-pretty">{sub}</p>
    </>
  );
}
