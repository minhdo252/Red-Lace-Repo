"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ReceiptText, Link2, AudioLines, Siren, ShieldCheck } from "lucide-react";
import { Screen } from "@/components/shell/Screen";
import { TopBar } from "@/components/shell/TopBar";
import { recentActivity } from "@/mocks/home";
import { cn } from "@/lib/utils";
import type { ActivityItem } from "@/mocks/types";

const kindCfg = {
  price: { icon: ReceiptText, tint: "bg-moss-soft text-moss-strong", href: "/price-check" },
  tour: { icon: Link2, tint: "bg-high/12 text-high", href: "/tour-check" },
  translate: { icon: AudioLines, tint: "bg-teal/15 text-teal-deep", href: "/translate" },
  sos: { icon: Siren, tint: "bg-danger/12 text-danger", href: "/sos" },
} as const;

const verdictChip: Record<string, { label: string; cls: string }> = {
  fair: { label: "Fair", cls: "bg-fair/12 text-fair" },
  safe: { label: "Safe", cls: "bg-fair/12 text-fair" },
  high: { label: "High risk", cls: "bg-high/12 text-high" },
  medium: { label: "Caution", cls: "bg-mid/18 text-[oklch(0.5_0.12_70)]" },
};

const extended: ActivityItem[] = [
  ...recentActivity,
  { id: "a4", kind: "price", title: "Coconut coffee", subtitle: "Cộng · Hoàn Kiếm · fair price", time: "2 days ago", verdict: "fair" },
  { id: "a5", kind: "translate", title: "Market haggling", subtitle: "Đồng Xuân · translated", time: "3 days ago", verdict: "safe" },
  { id: "a6", kind: "tour", title: "Sapa trek listing", subtitle: "instagram.com/sapa… · caution", time: "4 days ago", verdict: "medium" },
];

export default function ActivityPage() {
  const router = useRouter();
  return (
    <Screen>
      <TopBar title="Activity" subtitle="Every check Nón has run for you." onBack={() => router.push("/home")} />

      {/* summary strip */}
      <div className="mt-4 px-5">
        <div className="flex items-center gap-3 rounded-[var(--radius-card)] bg-moss-soft p-4">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-moss text-white">
            <ShieldCheck size={22} />
          </span>
          <div>
            <p className="font-display text-lg font-extrabold text-moss-strong">6 checks</p>
            <p className="text-xs text-ink-soft">2 warnings caught · you likely saved ~1.2M₫</p>
          </div>
        </div>
      </div>

      {/* list */}
      <div className="mt-4 px-5 pb-6">
        <div className="overflow-hidden rounded-[var(--radius-card)] bg-surface shadow-[var(--shadow-soft)]">
          {extended.map((a, i) => {
            const cfg = kindCfg[a.kind];
            const chip = a.verdict ? verdictChip[a.verdict] : null;
            return (
              <Link
                key={a.id}
                href={cfg.href}
                className={cn("flex items-center gap-3 p-3.5 active:bg-surface-2", i > 0 && "border-t border-line")}
              >
                <span className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-xl", cfg.tint)}>
                  <cfg.icon size={18} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-ink">{a.title}</p>
                  <p className="truncate text-xs text-ink-mute">{a.subtitle}</p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  {chip && (
                    <span className={cn("rounded-full px-2 py-0.5 text-[0.68rem] font-semibold", chip.cls)}>
                      {chip.label}
                    </span>
                  )}
                  <span className="text-[0.68rem] text-ink-mute">{a.time}</span>
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </Screen>
  );
}
