"use client";

import { useRef, useState } from "react";
import Image from "next/image";
import { AnimatePresence, motion } from "motion/react";
import {
  Camera,
  ImageUp,
  MapPin,
  Lock,
  MessageSquareQuote,
  RotateCcw,
  ReceiptText,
} from "lucide-react";
import { Screen } from "@/components/shell/Screen";
import { TopBar } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Gauge } from "@/components/ui/Gauge";
import { AnalysisLoader } from "@/components/ui/AnalysisLoader";
import { PriceTable } from "@/components/price/PriceTable";
import { useT } from "@/i18n";
import { usePhase, useFakeProgress } from "@/lib/hooks";
import { formatVnd } from "@/lib/utils";
import { receiptAnalysis, analysisSteps } from "@/mocks/price-check";

type P = "capture" | "analyzing" | "result";

export default function PriceCheckPage() {
  const t = useT("price");
  const { phase, setPhase } = usePhase<P>("capture");
  const [preview, setPreview] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const { index, percent } = useFakeProgress(
    analysisSteps.map((label) => ({ label })),
    3200,
    phase === "analyzing",
    () => setPhase("result"),
  );

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setPreview(URL.createObjectURL(f));
    setPhase("analyzing");
  };

  const reset = () => {
    setPreview(null);
    setPhase("capture");
  };

  const a = receiptAnalysis;
  const verdictLabel = a.verdict === "fair" ? t.fair : a.verdict === "mid" ? t.mid : t.high;

  return (
    <Screen>
      <TopBar title={t.title} subtitle={t.subtitle} />

      <AnimatePresence mode="wait">
        {phase === "capture" && (
          <motion.div
            key="capture"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-1 flex-col px-5 pt-3"
          >
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              onChange={onFile}
            />

            {/* capture frame */}
            <button
              onClick={() => fileRef.current?.click()}
              className="relative grid aspect-[4/5] w-full place-items-center overflow-hidden rounded-[var(--radius-lg)] border-2 border-dashed border-line-strong bg-surface active:scale-[0.99] transition-transform"
            >
              <div className="absolute inset-0 bg-[radial-gradient(120%_80%_at_50%_0%,var(--color-moss-soft),transparent)] opacity-60" />
              <div className="relative flex flex-col items-center gap-3 text-center">
                <span className="grid h-16 w-16 place-items-center rounded-2xl bg-moss text-white shadow-[0_12px_24px_-10px_var(--color-moss-strong)]">
                  <Camera size={30} />
                </span>
                <div>
                  <p className="font-display text-lg font-bold text-ink">{t.takePhoto}</p>
                  <p className="mt-0.5 text-sm text-ink-mute">Receipt · menu · price board</p>
                </div>
              </div>
              {/* corner guides */}
              {["left-4 top-4 border-l-2 border-t-2", "right-4 top-4 border-r-2 border-t-2", "left-4 bottom-4 border-l-2 border-b-2", "right-4 bottom-4 border-r-2 border-b-2"].map(
                (c) => (
                  <span key={c} className={`absolute h-7 w-7 rounded-md border-moss/50 ${c}`} />
                ),
              )}
            </button>

            <div className="mt-3 flex justify-center">
              <Button variant="secondary" size="lg" onClick={() => fileRef.current?.click()}>
                <ImageUp size={18} /> {t.upload}
              </Button>
            </div>

            <div className="mt-auto flex items-center gap-2 rounded-2xl bg-surface-2 p-3.5 text-xs text-ink-soft">
              <Lock size={15} className="shrink-0 text-moss-strong" />
              {t.disclaimer}
            </div>
          </motion.div>
        )}

        {phase === "analyzing" && (
          <motion.div
            key="analyzing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-1 flex-col"
          >
            <AnalysisLoader
              title={t.analyzing}
              steps={analysisSteps}
              activeIndex={index}
              percent={percent}
            />
          </motion.div>
        )}

        {phase === "result" && (
          <motion.div
            key="result"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-5 px-5 pb-8 pt-2"
          >
            <div className="flex items-center justify-between">
              <Chip tone="moss">
                <MapPin size={13} /> {a.area}
              </Chip>
              {preview ? (
                <Image
                  src={preview}
                  alt="receipt"
                  width={40}
                  height={40}
                  className="h-10 w-10 rounded-lg object-cover"
                />
              ) : (
                <span className="grid h-10 w-10 place-items-center rounded-lg bg-surface-2 text-ink-mute">
                  <ReceiptText size={18} />
                </span>
              )}
            </div>

            {/* verdict gauge */}
            <div className="rounded-[var(--radius-lg)] bg-surface p-5 shadow-[var(--shadow-soft)]">
              <Gauge
                verdict={a.verdict}
                label={verdictLabel}
                sublabel={a.overpayPct > 0 ? `${a.overpayPct}% over usual` : "within range"}
              />
              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-2xl bg-high/[0.06] p-3.5 text-center">
                  <p className="text-xs font-medium text-ink-mute">{t.youPaid}</p>
                  <p className="mt-0.5 font-display text-xl font-extrabold text-high">
                    {formatVnd(a.totalPaid)}
                  </p>
                </div>
                <div className="rounded-2xl bg-moss-soft p-3.5 text-center">
                  <p className="text-xs font-medium text-ink-mute">{t.reference}</p>
                  <p className="mt-0.5 font-display text-[0.95rem] font-extrabold text-moss-strong">
                    {formatVnd(a.refLow)}–{formatVnd(a.refHigh)}
                  </p>
                </div>
              </div>
            </div>

            {/* per item */}
            <div>
              <p className="mb-2 px-1 font-display text-[1.05rem] font-bold text-ink">
                {t.perItem}
              </p>
              <PriceTable items={a.items} />
            </div>

            {/* advice */}
            <div className="flex items-start gap-3 rounded-[var(--radius-card)] bg-teal/8 p-4">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-teal/20 text-teal-deep">
                <MessageSquareQuote size={18} />
              </span>
              <p className="text-[0.85rem] leading-snug text-ink-soft text-pretty">
                {t.disclaimer}
              </p>
            </div>

            <div className="flex gap-3">
              <Button variant="secondary" block onClick={reset}>
                <RotateCcw size={17} /> {t.takePhoto}
              </Button>
              <Button variant="primary" block>
                <MessageSquareQuote size={17} /> {t.askLocal}
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Screen>
  );
}
