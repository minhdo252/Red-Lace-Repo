"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { ChevronLeft, Phone, MapPin, Sparkles, ChevronRight, Plus, X, Star } from "lucide-react";
import { hotlines } from "@/mocks/emergency";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { Button } from "@/components/ui/Button";
import { useApp, useT } from "@/i18n";
import { cn } from "@/lib/utils";

const toneCls: Record<string, string> = {
  police: "bg-[oklch(0.55_0.15_25)]",
  ambulance: "bg-danger",
  fire: "bg-[oklch(0.62_0.16_45)]",
  hotline: "bg-teal-deep",
};

type SosNumber = { id: string; name: string; number: string };

export default function SosPage() {
  const t = useT("sos");
  const tc = useT("common");
  const router = useRouter();
  const { country } = useApp();

  const [numbers, setNumbers] = useState<SosNumber[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");

  // hydrate saved numbers from this device
  useEffect(() => {
    const raw = localStorage.getItem("nonai.sosNumbers");
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setNumbers(parsed);
      } catch {
        /* ignore corrupt storage */
      }
    }
  }, []);

  const persist = (list: SosNumber[]) => {
    setNumbers(list);
    localStorage.setItem("nonai.sosNumbers", JSON.stringify(list));
  };

  const saveNumber = () => {
    const n = name.trim();
    const p = phone.trim();
    if (!n || !p) return;
    persist([...numbers, { id: crypto.randomUUID(), name: n, number: p }]);
    setName("");
    setPhone("");
    setSheetOpen(false);
  };

  const removeNumber = (id: string) => persist(numbers.filter((c) => c.id !== id));

  const call = () => router.push("/sos/call");

  return (
    <div
      data-theme="dark"
      className="relative flex h-full flex-col bg-[radial-gradient(130%_100%_at_50%_-10%,#3a1f1f_0%,#241414_45%,#160f0f_100%)] text-white"
    >
      <header className="flex items-center gap-3 px-4 pb-1 pt-[max(env(safe-area-inset-top),0.75rem)]">
        <button
          onClick={() => router.push("/home")}
          aria-label="Back"
          className="grid h-10 w-10 place-items-center rounded-full bg-white/10 active:scale-95"
        >
          <ChevronLeft size={22} />
        </button>
        <h1 className="font-display text-lg font-bold">{t.title}</h1>
      </header>

      <div className="scroll-area no-scrollbar flex-1 overflow-y-auto px-5 pt-2">
        <p className="text-[0.92rem] text-white/70 text-pretty">{t.subtitle}</p>

        {/* AI interpreter banner — AI value up front */}
        <div className="mt-4 flex items-center gap-3 rounded-2xl border border-teal/25 bg-teal/10 p-3.5">
          <span className="relative grid h-10 w-10 shrink-0 place-items-center rounded-full bg-teal/20">
            <Sparkles size={18} className="text-teal" />
            <span className="absolute -right-0.5 -top-0.5 h-3 w-3 animate-pulse rounded-full bg-teal" />
          </span>
          <p className="text-[0.85rem] font-medium text-white/85">
            {t.interpreterOn}. <span className="text-white/60">{t.liveTranslate}.</span>
          </p>
        </div>

        {/* primary hotlines */}
        <div className="mt-4 space-y-3">
          {hotlines.map((h, i) => (
            <motion.button
              key={h.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              onClick={call}
              className="flex w-full items-center gap-4 rounded-2xl bg-white/8 p-4 text-left backdrop-blur-sm transition-transform active:scale-[0.98]"
            >
              <span
                className={cn(
                  "grid h-14 w-14 shrink-0 place-items-center rounded-2xl text-white",
                  toneCls[h.tone],
                )}
              >
                <h.icon size={26} />
              </span>
              <div className="flex-1">
                <p className="font-display text-lg font-bold">{h.name}</p>
                <p className="font-mono text-sm text-white/55">{h.number}</p>
              </div>
              <span className="grid h-11 w-11 place-items-center rounded-full bg-teal text-[#0f231d]">
                <Phone size={20} fill="currentColor" />
              </span>
            </motion.button>
          ))}
        </div>

        {/* embassy */}
        <button
          onClick={call}
          className="mt-3 flex w-full items-center gap-4 rounded-2xl bg-white/8 p-4 text-left backdrop-blur-sm transition-transform active:scale-[0.98]"
        >
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-white/12 text-3xl">
            {country.flag}
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-display text-lg font-bold">{t.embassy}</p>
            <p className="truncate text-sm text-white/55">{country.embassy}</p>
          </div>
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-teal text-[#0f231d]">
            <Phone size={20} fill="currentColor" />
          </span>
        </button>

        {/* share location */}
        <div className="mt-3 flex items-center gap-3 rounded-2xl bg-white/6 p-4">
          <MapPin size={20} className="shrink-0 text-teal" />
          <div className="flex-1">
            <p className="font-semibold">{t.shareLocation}</p>
            <p className="text-xs text-white/50">Hoàn Kiếm, Hà Nội · 21.0287, 105.8524</p>
          </div>
          <ChevronRight size={18} className="text-white/40" />
        </div>

        {/* your own saved numbers */}
        <div className="mb-8 mt-5">
          {numbers.length > 0 && (
            <p className="mb-2 px-1 text-sm font-semibold text-white/60">{t.yourNumbers}</p>
          )}
          <div className="space-y-3">
            {numbers.map((c) => (
              <motion.div
                key={c.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-3 rounded-2xl bg-white/8 p-3.5 backdrop-blur-sm"
              >
                <a
                  href={`tel:${c.number}`}
                  className="flex min-w-0 flex-1 items-center gap-4 transition-transform active:scale-[0.98]"
                >
                  <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-teal-deep text-white">
                    <Star size={24} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-display text-lg font-bold">{c.name}</p>
                    <p className="font-mono text-sm text-white/55">{c.number}</p>
                  </div>
                  <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-teal text-[#0f231d]">
                    <Phone size={20} fill="currentColor" />
                  </span>
                </a>
                <button
                  onClick={() => removeNumber(c.id)}
                  aria-label={`Remove ${c.name}`}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/10 text-white/55 transition active:scale-95 hover:text-white"
                >
                  <X size={16} />
                </button>
              </motion.div>
            ))}
          </div>

          <button
            onClick={() => setSheetOpen(true)}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-white/25 p-4 font-semibold text-white/80 transition-transform active:scale-[0.98]"
          >
            <Plus size={18} /> {t.addNumber}
          </button>
        </div>
      </div>

      {/* add-number sheet */}
      <BottomSheet open={sheetOpen} onClose={() => setSheetOpen(false)}>
        <h2 className="font-display text-lg font-bold text-ink">{t.addTitle}</h2>
        <div className="mt-4 space-y-3">
          <div>
            <label htmlFor="sos-name" className="text-sm font-medium text-ink-soft">
              {t.contactName}
            </label>
            <input
              id="sos-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t.namePlaceholder}
              className="mt-1 w-full rounded-xl border border-line bg-surface-2 px-3.5 py-3 text-ink outline-none transition focus:border-moss"
            />
          </div>
          <div>
            <label htmlFor="sos-phone" className="text-sm font-medium text-ink-soft">
              {t.contactPhone}
            </label>
            <input
              id="sos-phone"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              inputMode="tel"
              placeholder={t.phonePlaceholder}
              className="mt-1 w-full rounded-xl border border-line bg-surface-2 px-3.5 py-3 font-mono text-ink outline-none transition focus:border-moss"
            />
          </div>
        </div>
        <div className="mt-5 flex gap-3">
          <Button variant="secondary" block onClick={() => setSheetOpen(false)}>
            {tc.cancel}
          </Button>
          <Button variant="primary" block disabled={!name.trim() || !phone.trim()} onClick={saveNumber}>
            {t.save}
          </Button>
        </div>
      </BottomSheet>
    </div>
  );
}
