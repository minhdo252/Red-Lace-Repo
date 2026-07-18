"use client";

import { useState } from "react";
import {
  Globe,
  Flag,
  ShieldCheck,
  PhoneCall,
  Lock,
  Info,
  ChevronRight,
  LogOut,
  Sparkles,
  Check,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Screen } from "@/components/shell/Screen";
import { TopBar } from "@/components/shell/TopBar";
import { Mascot } from "@/components/ui/Mascot";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { useApp, useT, LOCALES, COUNTRIES } from "@/i18n";
import { cn } from "@/lib/utils";

export default function ProfilePage() {
  const t = useT("profile");
  const router = useRouter();
  const { name, country, setCountry, locale } = useApp();
  const localeMeta = LOCALES.find((l) => l.code === locale)!;
  const [countryOpen, setCountryOpen] = useState(false);

  return (
    <Screen>
      <TopBar title={t.title} onBack={() => router.push("/home")} />

      {/* identity card */}
      <div className="mt-3 px-5">
        <div className="grain relative overflow-hidden rounded-[var(--radius-lg)] bg-gradient-to-br from-moss to-moss-strong p-5 text-on-brand shadow-[var(--shadow-lift)]">
          <div className="absolute -right-6 -top-8 h-32 w-32 rounded-full bg-white/10 blur-xl" />
          <div className="relative flex items-center gap-4">
            <Mascot variant="face" size={64} ring />
            <div>
              <p className="font-display text-xl font-extrabold">{name}</p>
              <p className="text-sm text-white/70">{t.guest} · {country.flag} {country.name}</p>
            </div>
          </div>
          <div className="relative mt-4 inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1.5 text-xs font-semibold backdrop-blur-sm">
            <ShieldCheck size={13} /> 6 checks kept you safe this trip
          </div>
        </div>
      </div>

      {/* language row */}
      <div className="mt-5 px-5">
        <div className="flex items-center justify-between rounded-[var(--radius-card)] bg-surface p-4 shadow-[var(--shadow-soft)]">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-teal/15 text-teal-deep">
              <Globe size={20} />
            </span>
            <div>
              <p className="font-semibold text-ink">{t.language}</p>
              <p className="text-xs text-ink-mute">{localeMeta.label}</p>
            </div>
          </div>
          <LanguageSwitcher compact />
        </div>
      </div>

      {/* appearance */}
      <div className="mt-4 px-5">
        <div className="rounded-[var(--radius-card)] bg-surface p-1.5 shadow-[var(--shadow-soft)]">
          <ThemeToggle />
        </div>
      </div>

      {/* settings list */}
      <div className="mt-4 px-5">
        <div className="overflow-hidden rounded-[var(--radius-card)] bg-surface shadow-[var(--shadow-soft)]">
          <Row icon={Flag} tint="bg-straw/20 text-straw-deep" label={t.country} value={`${country.flag} ${country.name}`} onClick={() => setCountryOpen(true)} />
          <Row icon={PhoneCall} tint="bg-danger/10 text-danger" label={t.emergencyContacts} value="3 saved" />
          <Row icon={ShieldCheck} tint="bg-moss-soft text-moss-strong" label={t.trips} value="6" />
          <Row icon={Lock} tint="bg-surface-2 text-ink-soft" label={t.safety} />
          <Row icon={Info} tint="bg-surface-2 text-ink-soft" label={t.about} last />
        </div>
      </div>

      {/* privacy note */}
      <div className="mt-4 px-5">
        <div className="flex items-start gap-3 rounded-[var(--radius-card)] bg-teal/8 p-4">
          <Sparkles size={18} className="mt-0.5 shrink-0 text-teal-deep" />
          <p className="text-[0.82rem] leading-snug text-ink-soft text-pretty">{t.privacyNote}</p>
        </div>
      </div>

      {/* sign out */}
      <div className="mt-4 px-5">
        <button className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-card)] bg-surface p-4 font-semibold text-danger shadow-[var(--shadow-soft)] active:scale-[0.99]">
          <LogOut size={18} /> {t.signOut}
        </button>
      </div>

      {/* country picker — sets nationality (drives the SOS embassy card + backend session) */}
      <BottomSheet open={countryOpen} onClose={() => setCountryOpen(false)}>
        <h3 className="mb-1 font-display text-lg font-bold text-ink">{t.country}</h3>
        <p className="mb-4 text-sm text-ink-mute">Sets your embassy and emergency contacts.</p>
        <div className="space-y-1.5">
          {COUNTRIES.map((c) => {
            const active = c.code === country.code;
            return (
              <button
                key={c.code}
                onClick={() => {
                  setCountry(c);
                  setCountryOpen(false);
                }}
                className={cn(
                  "flex w-full items-center gap-3 rounded-2xl px-3.5 py-3 text-left transition-colors",
                  active ? "bg-moss-soft" : "hover:bg-surface-2",
                )}
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-moss-soft text-lg">
                  {c.flag}
                </span>
                <span className="flex-1">
                  <span className={cn("block font-semibold", active ? "text-forest" : "text-ink")}>
                    {c.name}
                  </span>
                  <span className={cn("block text-xs", active ? "text-forest/70" : "text-ink-mute")}>
                    {c.embassy}
                  </span>
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
      </BottomSheet>
    </Screen>
  );
}

function Row({
  icon: Icon,
  tint,
  label,
  value,
  last,
  onClick,
}: {
  icon: React.ComponentType<{ size?: number }>;
  tint: string;
  label: string;
  value?: string;
  last?: boolean;
  onClick?: () => void;
}) {
  return (
    <button onClick={onClick} className={cn("flex w-full items-center gap-3 p-3.5 text-left active:bg-surface-2", !last && "border-b border-line")}>
      <span className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-xl", tint)}>
        <Icon size={18} />
      </span>
      <span className="flex-1 font-semibold text-ink">{label}</span>
      {value && <span className="text-sm text-ink-mute">{value}</span>}
      <ChevronRight size={18} className="text-ink-mute" />
    </button>
  );
}
