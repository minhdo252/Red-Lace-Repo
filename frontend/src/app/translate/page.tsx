"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { ChevronLeft, Mic, Square, RotateCcw, ArrowLeftRight } from "lucide-react";
import { ListeningOrb, Waveform } from "@/components/translate/ListeningOrb";
import { ChatBubble } from "@/components/translate/ChatBubble";
import { ScamBanner } from "@/components/translate/ScamBanner";
import { TranscriptSummary } from "@/components/translate/TranscriptSummary";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { useApp, useT } from "@/i18n";
import { usePhase, useTimer, useStaggeredReveal } from "@/lib/hooks";
import { formatDuration, delay } from "@/lib/utils";
import { blobToBase64, chatRequest, localeToNativeLanguage, toTranslateTurn } from "@/lib/api";
import { conversation } from "@/mocks/translate";
import type { TranslateTurn } from "@/mocks/types";

type P = "idle" | "listening" | "processing" | "result";

export default function TranslatePage() {
  const t = useT("translate");
  const router = useRouter();
  const { locale, country, ensureSession } = useApp();
  const { phase, setPhase } = usePhase<P>("idle");
  const { seconds, reset } = useTimer(phase === "listening");

  const [turns, setTurns] = useState<TranslateTurn[]>([]);
  const [prices, setPrices] = useState<number[]>([]);
  const [usingBackend, setUsingBackend] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const revealing = phase === "result";
  const shown = useStaggeredReveal(turns, revealing, 900);
  const allShown = turns.length > 0 && shown.length === turns.length;

  const startRecording = async (): Promise<boolean> => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      rec.start();
      recorderRef.current = rec;
      return true;
    } catch {
      return false;
    }
  };

  const stopRecording = (): Promise<Blob | null> =>
    new Promise((resolve) => {
      const rec = recorderRef.current;
      if (!rec) return resolve(null);
      rec.onstop = () => {
        rec.stream.getTracks().forEach((tr) => tr.stop());
        resolve(new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" }));
      };
      rec.stop();
      recorderRef.current = null;
    });

  // Begin a new utterance. If the mic is unavailable, stop() falls back to the
  // scripted mock conversation so the screen still demos end to end.
  const listen = async () => {
    reset();
    await startRecording();
    setPhase("listening");
  };

  const stop = async () => {
    setPhase("processing");
    const blob = await stopRecording();
    if (!blob || !blob.size) {
      await delay(1000);
      setTurns(conversation);
      setUsingBackend(false);
      setPhase("result");
      return;
    }
    const audioBase64 = await blobToBase64(blob);
    const fmt = blob.type.includes("ogg") ? "ogg" : "webm";
    const sid = await ensureSession();
    const env = await chatRequest({
      session_id: sid,
      native_language: localeToNativeLanguage(locale),
      nationality: country.code,
      speaker_role: "unknown",
      audio_base64: audioBase64,
      audio_format: fmt,
    });
    if (env.source === "backend") {
      const details = (env.translation_details ?? {}) as { detected_language?: string };
      const spoken = env.detected_language || details.detected_language;
      const turn = toTranslateTurn(env, spoken === "vi" ? "vendor" : "tourist");
      setTurns((ts) => [...ts, turn]);
      setPrices((ps) => [...ps, ...(env.normalized_prices_vnd ?? [])]);
      setUsingBackend(true);
    } else {
      await delay(800);
      setTurns(conversation);
      setUsingBackend(false);
    }
    setPhase("result");
  };

  const restart = () => {
    setTurns([]);
    setPrices([]);
    setUsingBackend(false);
    reset();
    setPhase("idle");
  };

  const summaryData = usingBackend
    ? {
        topic: (turns[0]
          ? turns[0].speaker === "you"
            ? turns[0].en
            : turns[0].vi
          : "Live conversation"
        ).slice(0, 70),
        pricesHeard: prices.map((p, i) => ({
          label: `Price heard ${i + 1}`,
          value: `${p.toLocaleString()}₫`,
          tone: "mid" as const,
        })),
        scamCount: turns.filter((tn) => tn.scam).length,
      }
    : undefined;

  return (
    <div className="va-bg relative flex h-full flex-col text-ink">
      <header className="flex items-center gap-3 px-4 pb-2 pt-[max(env(safe-area-inset-top),0.75rem)]">
        <button
          onClick={() => router.back()}
          aria-label="Back"
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-surface text-ink shadow-[var(--shadow-soft)] active:scale-95"
        >
          <ChevronLeft size={22} />
        </button>
        <div className="flex-1">
          <h1 className="font-display font-bold text-ink">{t.title}</h1>
          <p className="text-[0.72rem] text-ink-mute">{t.subtitle}</p>
        </div>
        <LanguageSwitcher compact />
      </header>

      {/* language pair */}
      <div className="flex justify-center pb-1">
        <div className="inline-flex items-center gap-2 rounded-full bg-surface px-3.5 py-1.5 text-sm font-semibold text-ink shadow-[var(--shadow-soft)]">
          <span>{locale.toUpperCase()}</span>
          <ArrowLeftRight size={14} className="text-straw-deep" />
          <span>VI</span>
        </div>
      </div>

      {/* body */}
      <div className="scroll-area no-scrollbar flex-1 overflow-y-auto px-4">
        <AnimatePresence mode="wait">
          {phase !== "result" ? (
            <motion.div
              key="orb"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex min-h-full flex-col items-center justify-center pb-8"
            >
              <button
                onClick={() => {
                  if (phase === "idle") void listen();
                }}
                aria-label={t.tapToSpeak}
                className="flex flex-col items-center active:scale-[0.99]"
              >
                <ListeningOrb state={phase === "idle" ? "idle" : phase} />
                <h2 className="mt-1 font-display text-xl font-bold text-ink">
                  {phase === "idle" && t.tapToSpeak}
                  {phase === "listening" && t.listening}
                  {phase === "processing" && t.processing}
                </h2>
              </button>
              {phase === "listening" && (
                <>
                  <div className="mt-4">
                    <Waveform active />
                  </div>
                  <p className="mt-3 font-mono text-sm text-ink-mute">{formatDuration(seconds)}</p>
                </>
              )}
            </motion.div>
          ) : (
            <motion.div key="chat" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-3 py-3">
              {shown.map((turn, i) => (
                <div key={i} className="space-y-3">
                  <ChatBubble turn={turn} youLabel={t.you} themLabel={t.them} />
                  {turn.scam && (
                    <ScamBanner
                      title={t.scamTitle}
                      pattern={turn.scam.pattern}
                      advice={turn.scam.advice}
                      actionLabel={t.scamAction}
                    />
                  )}
                </div>
              ))}
              {allShown && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                  className="pt-2"
                >
                  <TranscriptSummary title={t.summaryTitle} priceLabel={t.priceHeard} data={summaryData} />
                </motion.div>
              )}
              <div className="h-2" />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* controls */}
      <div className="shrink-0 px-4 pb-[max(env(safe-area-inset-bottom),1rem)] pt-2">
        {phase === "idle" && (
          <button
            onClick={() => void listen()}
            aria-label={t.tapToSpeak}
            className="mx-auto grid h-[4.5rem] w-[4.5rem] place-items-center rounded-full bg-gradient-to-br from-straw to-straw-deep text-[#3a2c06] shadow-[var(--shadow-lift)] transition-transform active:scale-95"
          >
            <Mic size={30} strokeWidth={2.3} />
          </button>
        )}
        {phase === "listening" && (
          <button
            onClick={stop}
            aria-label={t.tapToStop}
            className="mx-auto grid h-[4.5rem] w-[4.5rem] place-items-center rounded-full bg-danger text-white transition-transform active:scale-95"
            style={{ animation: "sos-pulse 1.8s ease-out infinite" }}
          >
            <Square size={26} fill="currentColor" />
          </button>
        )}
        {phase === "result" && (
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => void listen()}
              aria-label={t.tapToSpeak}
              className="grid h-14 w-14 place-items-center rounded-full bg-gradient-to-br from-straw to-straw-deep text-[#3a2c06] shadow-[var(--shadow-lift)] transition-transform active:scale-95"
            >
              <Mic size={24} strokeWidth={2.3} />
            </button>
            <button
              onClick={restart}
              className="flex items-center gap-2 rounded-full bg-surface px-5 py-3 font-semibold text-ink shadow-[var(--shadow-soft)] active:scale-95"
            >
              <RotateCcw size={18} /> {t.newConversation}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
