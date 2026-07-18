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
import { AnalysisLoader } from "@/components/ui/AnalysisLoader";
import { useApp, useT } from "@/i18n";
import { usePhase, useFakeProgress } from "@/lib/hooks";
import { formatVnd, delay } from "@/lib/utils";
import { analysisSteps } from "@/mocks/price-check";
import { chatRequest, fileToBase64, localeToNativeLanguage, type PriceAnalysis } from "@/lib/api";

type P = "capture" | "analyzing" | "result";

/** Real backend outcome for a receipt photo (no mock): a read price verdict, a
 * "retake the photo" signal, or a "backend unreachable" error. */
type LiveResult =
  | { kind: "ok"; reply: string; prices: number[]; region: string | null; analysis: PriceAnalysis | null }
  | { kind: "retake"; reply: string }
  | { kind: "error" };

export default function PriceCheckPage() {
  const t = useT("price");
  const { locale, country, ensureSession } = useApp();
  const { phase, setPhase } = usePhase<P>("capture");
  const [preview, setPreview] = useState<string | null>(null);
  const [live, setLive] = useState<LiveResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Purely-visual analysis animation; the real transition to "result" is driven by
  // onFile awaiting the backend turn (mirrors tour-check).
  const { index, percent } = useFakeProgress(
    analysisSteps.map((label) => ({ label })),
    3200,
    phase === "analyzing",
  );

  // Photograph a receipt/menu -> POST /api/chat (images, receipt mode). Real input
  // only: show the backend's price verdict + prices, a "retake the photo" prompt when
  // it couldn't be read, or a graceful error when the backend is unreachable. No mock.
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setPreview(URL.createObjectURL(f));
    e.target.value = "";
    // Read the file before showing the loader so a FileReader failure can't strand
    // the user on the analysis spinner (mirrors Home's onPickPhoto ordering).
    const base64 = await fileToBase64(f);
    setPhase("analyzing");
    const sid = await ensureSession();
    const [env] = await Promise.all([
      chatRequest({
        session_id: sid,
        native_language: localeToNativeLanguage(locale),
        nationality: country.code,
        speaker_role: "tourist",
        images: [{ image_base64: base64, mode: "receipt" }],
      }),
      delay(1200),
    ]);
    if (env.source !== "backend") {
      setLive({ kind: "error" });
    } else if (env.needs_retake) {
      setLive({ kind: "retake", reply: env.reply ?? "" });
    } else {
      setLive({
        kind: "ok",
        reply: env.reply ?? "",
        prices: env.normalized_prices_vnd ?? [],
        region: env.resolved_region ?? null,
        analysis: env.price_analysis ?? null,
      });
    }
    setPhase("result");
  };

  const reset = () => {
    setPreview(null);
    setLive(null);
    setPhase("capture");
  };

  const areaLabel = live && live.kind === "ok" ? live.region : null;

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
              {areaLabel ? (
                <Chip tone="moss">
                  <MapPin size={13} /> {areaLabel}
                </Chip>
              ) : (
                <span />
              )}
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

            {live?.kind === "error" && (
              <div className="rounded-[var(--radius-lg)] bg-surface p-5 shadow-[var(--shadow-soft)]">
                <p className="text-[0.9rem] leading-snug text-ink-soft text-pretty">
                  I couldn&apos;t reach the assistant right now. Please check your connection and try again.
                </p>
              </div>
            )}

            {live?.kind === "retake" && (
              <div className="rounded-[var(--radius-lg)] bg-surface p-5 shadow-[var(--shadow-soft)]">
                <div className="flex items-start gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-mid/20 text-[oklch(0.5_0.12_70)]">
                    <Camera size={18} />
                  </span>
                  <p className="text-[0.9rem] leading-snug text-ink-soft text-pretty">
                    {live.reply ||
                      "I couldn't read that photo. Please retake a clearer, closer photo of the menu."}
                  </p>
                </div>
              </div>
            )}

            {live?.kind === "ok" && (
              <div className="rounded-[var(--radius-lg)] bg-surface p-5 shadow-[var(--shadow-soft)]">
                <div className="flex items-start gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-teal/20 text-teal-deep">
                    <MessageSquareQuote size={18} />
                  </span>
                  <p className="whitespace-pre-line text-[0.9rem] leading-snug text-ink-soft text-pretty">
                    {live.reply || t.disclaimer}
                  </p>
                </div>

                {live.analysis?.items?.length ? (
                  <div className="mt-4 space-y-2 border-t border-line pt-4">
                    {live.analysis.items.map((it, i) => (
                      <div key={i} className="flex items-center justify-between gap-3 text-sm">
                        <span className="truncate text-ink">{it.item}</span>
                        <span className="flex shrink-0 items-center gap-2">
                          {typeof it.observed_price === "number" && (
                            <span className="font-extrabold text-ink">{formatVnd(it.observed_price)}</span>
                          )}
                          {it.overpriced ? (
                            <span className="rounded-full bg-high/[0.12] px-2 py-0.5 text-xs font-semibold text-high">
                              {typeof it.price_diff_pct === "number" ? `+${Math.round(it.price_diff_pct)}%` : "high"}
                            </span>
                          ) : (
                            <span className="rounded-full bg-moss-soft px-2 py-0.5 text-xs font-semibold text-moss-strong">
                              fair
                            </span>
                          )}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : live.prices.length > 0 ? (
                  <div className="mt-4 border-t border-line pt-4">
                    <p className="mb-2 text-xs font-semibold text-ink-mute">Prices found</p>
                    <div className="flex flex-wrap gap-2">
                      {live.prices.map((p, i) => (
                        <span
                          key={i}
                          className="rounded-full bg-moss-soft px-3 py-1.5 text-sm font-extrabold text-moss-strong"
                        >
                          {formatVnd(p)}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            )}

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
