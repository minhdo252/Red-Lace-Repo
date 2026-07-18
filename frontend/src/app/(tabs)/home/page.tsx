"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { Equal, Plus, Camera, Mic, ArrowUp } from "lucide-react";
import { Mascot } from "@/components/ui/Mascot";
import { AppDrawer } from "@/components/shell/AppDrawer";
import { AssistantReply } from "@/components/assistant/AssistantReply";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useApp, useT } from "@/i18n";
import { type AssistantMessage, type AssistantAction } from "@/mocks/assistant";
import {
  blobToBase64,
  chatRequest,
  fileToBase64,
  localeToNativeLanguage,
  toAssistantMessage,
} from "@/lib/api";

type Phase = "home" | "thinking" | "chat";

let uid = 0;
const nextId = (p: string) => `${p}-${++uid}`;

export default function HomePage() {
  const t = useT("assistant");
  const ht = useT("home");
  const { name, locale, country, ensureSession } = useApp();
  const router = useRouter();

  const [phase, setPhase] = useState<Phase>("home");
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [input, setInput] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [listening, setListening] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const scrollEnd = () =>
    requestAnimationFrame(() =>
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }),
    );

  const historyFromMessages = (msgs: AssistantMessage[]) =>
    msgs
      .filter((m) => m.text)
      .slice(-10)
      .map((m) => ({
        role: m.role === "ai" ? ("assistant" as const) : ("user" as const),
        content: m.text,
      }));

  /** Append a plain AI note (errors, "no audio") and drop into chat view — never a
   * fabricated answer, just a real status message. */
  const pushAiNote = (text: string) => {
    setMessages((m) => [...m, { id: nextId("a"), role: "ai", text, verdict: "caution" }]);
    setPhase("chat");
    scrollEnd();
  };

  /**
   * Append the user's message, run the real backend turn (POST /api/chat), then
   * append the real AI reply. No mock/canned answers: if the backend is
   * unreachable we say so; if a photo can't be read we ask the user to retake it.
   */
  const send = async (
    userMsg: AssistantMessage,
    payload: {
      text?: string;
      audio_base64?: string;
      audio_format?: string;
      images?: { image_base64: string; mode: string }[];
    },
    updateUserFromTranscript = false,
  ) => {
    const priorHistory = historyFromMessages(messages);
    setMessages((m) => [...m, userMsg]);
    setPhase("thinking");
    scrollEnd();

    const sessionId = await ensureSession();
    const env = await chatRequest({
      session_id: sessionId,
      native_language: localeToNativeLanguage(locale),
      nationality: country.code,
      speaker_role: "tourist",
      history: priorHistory,
      ...payload,
    });

    let aiMsg: AssistantMessage;
    if (env.source === "backend") {
      if (updateUserFromTranscript && env.source_text) {
        const transcript = env.source_text;
        setMessages((m) => m.map((x) => (x.id === userMsg.id ? { ...x, text: transcript } : x)));
      }
      aiMsg = env.needs_retake
        ? {
            id: nextId("a"),
            role: "ai",
            text:
              env.reply ||
              "I couldn't read that photo — please retake a clearer photo of the menu.",
            verdict: "caution",
            actions: [{ label: "Retake photo", kind: "retake" }],
          }
        : toAssistantMessage(env, nextId("a"));
    } else {
      // Backend unreachable — surface a real error, never a fake answer.
      aiMsg = {
        id: nextId("a"),
        role: "ai",
        text: "I couldn't reach the assistant right now. Please check your connection and try again.",
        verdict: "caution",
      };
    }
    setMessages((m) => [...m, aiMsg]);
    setPhase("chat");
    scrollEnd();
  };

  const onSend = () => {
    const q = input.trim();
    if (!q) return;
    setInput("");
    const userMsg: AssistantMessage = { id: nextId("u"), role: "user", text: q };
    void send(userMsg, { text: q });
  };

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

  const onMic = async () => {
    if (phase === "thinking") return;
    // Second tap: stop recording and send the real captured audio.
    if (listening) {
      setListening(false);
      const blob = await stopRecording();
      if (!blob || !blob.size) {
        pushAiNote("I didn't catch any audio — please try again.");
        return;
      }
      const audioBase64 = await blobToBase64(blob);
      const fmt = blob.type.includes("ogg") ? "ogg" : "webm";
      void send(
        { id: nextId("u"), role: "user", text: "🎤 …" },
        { audio_base64: audioBase64, audio_format: fmt },
        true,
      );
      return;
    }
    // First tap: begin recording. No mic access = a real error, not a scripted demo.
    const ok = await startRecording();
    if (!ok) {
      pushAiNote("I can't access the microphone. Please enable mic access and try again.");
      return;
    }
    setListening(true);
  };

  const onPickPhoto = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    e.target.value = "";
    const base64 = await fileToBase64(file);
    const userMsg: AssistantMessage = { id: nextId("u"), role: "user", text: "", image: url };
    void send(userMsg, { text: "", images: [{ image_base64: base64, mode: "receipt" }] });
  };

  const newChat = () => {
    setMessages([]);
    setPhase("home");
  };

  const onAction = (a: AssistantAction) => {
    if (a.kind === "retake") {
      fileRef.current?.click();
      return;
    }
    const map: Record<string, string> = {
      grab: "/map", police: "/sos", translate: "/translate",
      price: "/price-check", tour: "/tour-check", map: "/map",
    };
    router.push(map[a.kind] ?? "/home");
  };

  const typing = input.trim().length > 0;

  return (
    <div className="home-bg relative flex h-full flex-col text-ink">
      {/* top bar */}
      <header className="relative z-10 flex items-center gap-1.5 px-4 pb-2 pt-[max(env(safe-area-inset-top),0.75rem)]">
        <button
          onClick={() => setDrawer(true)}
          aria-label="Menu"
          className="grid h-10 w-10 place-items-center rounded-full bg-surface text-ink shadow-[var(--shadow-soft)] active:scale-95"
        >
          <Equal size={22} strokeWidth={2.5} />
        </button>
        <span className="ml-1 flex-1 font-display text-lg font-extrabold tracking-tight">
          Nón<span className="text-accent">AI</span>
        </span>
        <ThemeToggle compact />
        {phase !== "home" && (
          <button
            onClick={newChat}
            aria-label="New chat"
            className="grid h-10 w-10 place-items-center rounded-full bg-surface text-ink-soft shadow-[var(--shadow-soft)] active:scale-95"
          >
            <Plus size={20} />
          </button>
        )}
        <button onClick={() => router.push("/profile")} aria-label="Profile">
          <Mascot variant="face" size={38} ring />
        </button>
      </header>

      {/* body */}
      <div ref={scrollRef} className="scroll-area no-scrollbar relative z-10 flex-1 overflow-y-auto px-5">
        <AnimatePresence mode="wait">
          {phase === "home" ? (
            <motion.div
              key="home"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex min-h-full flex-col items-center justify-center pb-10 text-center"
            >
              <div className="relative">
                <span
                  aria-hidden
                  className="absolute left-1/2 top-1/2 h-52 w-52 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent/20 blur-3xl"
                />
                <Mascot variant="full" size={138} float className="relative" />
              </div>
              <h1 className="mt-7 font-display text-[2.1rem] font-extrabold leading-[1.1] tracking-tight text-ink">
                {ht.greeting}, <span className="text-accent">{name}</span>
              </h1>
              <p className="mt-2.5 max-w-[24ch] text-[0.98rem] font-medium text-ink-soft text-pretty">
                {t.greeting}
              </p>
            </motion.div>
          ) : (
            <motion.div
              key="chat"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="space-y-4 py-3"
            >
              {messages.map((m) =>
                m.role === "user" ? (
                  <motion.div
                    key={m.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex justify-end"
                  >
                    <div className="max-w-[85%] rounded-2xl rounded-br-md bg-accent px-4 py-3 text-[0.95rem] font-medium text-on-brand">
                      {m.image && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={m.image}
                          alt="Your photo"
                          className="mb-0.5 max-h-56 w-full rounded-xl object-cover"
                        />
                      )}
                      {m.text}
                    </div>
                  </motion.div>
                ) : (
                  <div key={m.id} className="flex gap-2.5">
                    <Mascot variant="face" size={30} ring className="mt-1 shrink-0" />
                    <AssistantReply msg={m} doThisLabel={t.doThis} onAction={onAction} />
                  </div>
                ),
              )}
              {phase === "thinking" && (
                <div className="flex items-center gap-2.5">
                  <Mascot variant="face" size={30} ring className="shrink-0" />
                  <div className="flex items-center gap-2 rounded-2xl rounded-bl-md bg-surface px-4 py-3 text-sm text-ink-mute shadow-[var(--shadow-soft)]">
                    <span className="flex gap-1">
                      {[0, 0.15, 0.3].map((d) => (
                        <motion.span
                          key={d}
                          className="h-1.5 w-1.5 rounded-full bg-accent"
                          animate={{ opacity: [0.3, 1, 0.3], y: [0, -2, 0] }}
                          transition={{ duration: 0.9, repeat: Infinity, delay: d }}
                        />
                      ))}
                    </span>
                    {t.thinking}
                  </div>
                </div>
              )}
              <div className="h-2" />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* listening pill */}
      <AnimatePresence>
        {listening && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="relative z-10 mx-auto mb-1 flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-on-brand shadow-[var(--shadow-soft)]"
          >
            <span className="flex items-end gap-0.5">
              {[0, 0.15, 0.3, 0.45].map((d) => (
                <motion.span
                  key={d}
                  className="w-0.5 rounded-full bg-on-brand"
                  animate={{ height: [4, 12, 4] }}
                  transition={{ duration: 0.7, repeat: Infinity, delay: d }}
                />
              ))}
            </span>
            {t.listening}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ask bar */}
      <div className="relative z-10 shrink-0 px-4 pb-[max(env(safe-area-inset-bottom),0.75rem)] pt-2">
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          onChange={onPickPhoto}
          className="hidden"
        />
        <div className="flex items-center gap-2 rounded-[1.6rem] border border-line bg-surface p-1.5 shadow-[var(--shadow-lift)]">
          <button
            onClick={() => fileRef.current?.click()}
            aria-label="Scan a receipt or price"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent/12 text-accent active:scale-95"
          >
            <Camera size={20} />
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSend()}
            placeholder={t.askPlaceholder}
            className="flex-1 bg-transparent text-[0.9rem] text-ink placeholder:text-ink-mute focus:outline-none"
          />
          {typing ? (
            <button
              onClick={onSend}
              aria-label="Send"
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent text-on-brand active:scale-95"
            >
              <ArrowUp size={20} strokeWidth={2.6} />
            </button>
          ) : (
            <button
              onClick={onMic}
              aria-label="Speak"
              className={cnMic(listening)}
            >
              <Mic size={19} strokeWidth={2.4} />
            </button>
          )}
        </div>
      </div>

      <AppDrawer open={drawer} onClose={() => setDrawer(false)} onNewChat={newChat} />
    </div>
  );
}

function cnMic(listening: boolean) {
  return [
    "grid h-10 w-10 shrink-0 place-items-center rounded-full text-[#0f231d] transition-transform active:scale-95",
    "bg-gradient-to-br from-teal to-teal-deep",
    listening ? "ring-4 ring-teal/40 scale-105" : "",
  ].join(" ");
}
