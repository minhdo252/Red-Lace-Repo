"use client";

import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import {
  Plus,
  AudioLines,
  ReceiptText,
  Link2,
  Siren,
  Map as MapIcon,
  Clock3,
  Settings,
  MessageSquare,
} from "lucide-react";
import { Mascot } from "@/components/ui/Mascot";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useApp, useT } from "@/i18n";
import { cn } from "@/lib/utils";

const recents = [
  "Taxi fare to Hoan Kiem",
  "Ha Long cruise — is it real?",
  "Bún chả receipt check",
];

export function AppDrawer({
  open,
  onClose,
  onNewChat,
}: {
  open: boolean;
  onClose: () => void;
  onNewChat: () => void;
}) {
  const router = useRouter();
  const home = useT("home");
  const nav = useT("nav");
  const { name, country } = useApp();

  const tools = [
    { icon: AudioLines, label: home.actions.translate, href: "/translate", tint: "text-teal-deep" },
    { icon: ReceiptText, label: home.actions.price, href: "/price-check", tint: "text-moss-strong" },
    { icon: Link2, label: home.actions.tour, href: "/tour-check", tint: "text-straw-deep" },
    { icon: Siren, label: home.actions.sos, href: "/sos", tint: "text-danger" },
    { icon: MapIcon, label: nav.map, href: "/map", tint: "text-ink-soft" },
    { icon: Clock3, label: nav.activity, href: "/activity", tint: "text-ink-soft" },
  ];

  const go = (href: string) => {
    onClose();
    router.push(href);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute inset-0 z-50 flex"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.button
            aria-label="Close menu"
            onClick={onClose}
            className="absolute inset-0 bg-forest-deep/40 backdrop-blur-[2px]"
          />
          <motion.aside
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 320 }}
            className="relative z-10 flex h-full w-[84%] max-w-[330px] flex-col bg-surface pt-[max(env(safe-area-inset-top),1rem)] shadow-[8px_0_40px_-12px_rgba(20,40,34,0.35)]"
          >
            {/* header */}
            <div className="flex items-center gap-2.5 px-5 pb-4">
              <Mascot variant="face" size={40} ring />
              <span className="font-display text-xl font-extrabold tracking-tight text-ink">
                Nón<span className="text-moss">AI</span>
              </span>
            </div>

            {/* new chat */}
            <div className="px-3">
              <button
                onClick={() => {
                  onClose();
                  onNewChat();
                }}
                className="flex w-full items-center gap-3 rounded-full bg-moss-soft px-4 py-3 text-left font-semibold text-moss-strong transition-transform active:scale-[0.98]"
              >
                <Plus size={19} /> New chat
              </button>
            </div>

            <div className="scroll-area no-scrollbar mt-4 flex-1 overflow-y-auto px-3">
              {/* recents */}
              <p className="px-2 pb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-ink-mute">
                Recent
              </p>
              {recents.map((r) => (
                <button
                  key={r}
                  onClick={() => go("/home")}
                  className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left text-sm text-ink-soft transition-colors active:bg-surface-2"
                >
                  <MessageSquare size={16} className="shrink-0 text-ink-mute" />
                  <span className="truncate">{r}</span>
                </button>
              ))}

              {/* tools */}
              <p className="mt-4 px-2 pb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-ink-mute">
                Protection tools
              </p>
              {tools.map((t) => (
                <button
                  key={t.href}
                  onClick={() => go(t.href)}
                  className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors active:bg-surface-2"
                >
                  <t.icon size={19} className={cn("shrink-0", t.tint)} />
                  <span className="font-medium text-ink">{t.label}</span>
                </button>
              ))}

              {/* appearance */}
              <p className="mt-4 px-2 pb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-ink-mute">
                Appearance
              </p>
              <ThemeToggle />
            </div>

            {/* footer */}
            <div className="border-t border-line px-3 py-3">
              <div className="mb-1 flex items-center justify-between px-1">
                <button
                  onClick={() => go("/profile")}
                  className="flex flex-1 items-center gap-3 rounded-xl p-1.5 text-left active:bg-surface-2"
                >
                  <Mascot variant="face" size={34} ring />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-ink">{name}</span>
                    <span className="block truncate text-xs text-ink-mute">
                      {country.flag} {country.name}
                    </span>
                  </span>
                </button>
                <button
                  onClick={() => go("/profile")}
                  aria-label="Settings"
                  className="grid h-9 w-9 place-items-center rounded-full text-ink-mute active:bg-surface-2"
                >
                  <Settings size={18} />
                </button>
              </div>
              <div className="px-1">
                <LanguageSwitcher />
              </div>
            </div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
