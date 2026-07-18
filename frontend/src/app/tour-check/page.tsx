"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  Link2,
  Sparkles,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  History,
  Users,
  TrendingDown,
  TriangleAlert,
  Info,
  CircleAlert,
  RotateCcw,
  Clipboard,
} from "lucide-react";
import { Screen } from "@/components/shell/Screen";
import { TopBar } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/Button";
import { AnalysisLoader } from "@/components/ui/AnalysisLoader";
import { useT } from "@/i18n";
import { usePhase, useFakeProgress } from "@/lib/hooks";
import { cn, formatVnd } from "@/lib/utils";
import { analysisSteps, riskyTour, cleanTour } from "@/mocks/tour-check";
import type { TourReport } from "@/mocks/types";

type P = "input" | "analyzing" | "report";
const SAMPLE = "facebook.com/HalongLuxuryCruise.Cheap";

const riskCfg = {
  high: { label: "High scam risk", icon: ShieldAlert, cls: "bg-danger text-white", chip: "text-danger" },
  medium: { label: "Be careful", icon: ShieldQuestion, cls: "bg-mid text-[#3a2c05]", chip: "text-mid" },
  low: { label: "Looks legit", icon: ShieldCheck, cls: "bg-moss text-white", chip: "text-moss-strong" },
} as const;

const sevIcon = { danger: CircleAlert, warn: TriangleAlert, info: Info } as const;
const sevCls = {
  danger: "bg-danger/10 text-danger",
  warn: "bg-mid/15 text-[oklch(0.5_0.12_70)]",
  info: "bg-surface-2 text-ink-soft",
} as const;

export default function TourCheckPage() {
  const t = useT("tour");
  const { phase, setPhase } = usePhase<P>("input");
  const [url, setUrl] = useState("");

  const report: TourReport =
    /cheap|halong|luxury|deal/i.test(url) || url === SAMPLE ? riskyTour : cleanTour;

  const { index, percent } = useFakeProgress(
    analysisSteps.map((label) => ({ label })),
    3400,
    phase === "analyzing",
    () => setPhase("report"),
  );

  const run = () => url.trim() && setPhase("analyzing");
  const rc = riskCfg[report.risk];

  return (
    <Screen>
      <TopBar title={t.title} subtitle={t.subtitle} />

      <AnimatePresence mode="wait">
        {phase === "input" && (
          <motion.div
            key="input"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-1 flex-col px-5 pt-3"
          >
            <div className="rounded-[var(--radius-lg)] bg-surface p-5 shadow-[var(--shadow-soft)]">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-straw/20 text-straw-deep">
                <Link2 size={24} />
              </span>
              <p className="mt-3 font-display font-bold text-ink">{t.subtitle}</p>
              <div className="mt-3 flex items-center gap-2 rounded-2xl border border-line bg-bg px-3.5 py-3">
                <Link2 size={17} className="shrink-0 text-ink-mute" />
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && run()}
                  placeholder={t.placeholder}
                  className="flex-1 bg-transparent text-sm text-ink placeholder:text-ink-mute focus:outline-none"
                />
              </div>
              <button
                onClick={() => setUrl(SAMPLE)}
                className="mt-2.5 inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1.5 text-xs font-semibold text-ink-soft active:scale-95"
              >
                <Clipboard size={13} /> {t.sampleLink}
              </button>
            </div>

            <div className="mt-4 flex items-center gap-3 rounded-2xl bg-teal/8 p-4">
              <Sparkles size={20} className="shrink-0 text-teal-deep" />
              <p className="text-[0.85rem] leading-snug text-ink-soft text-pretty">
                Nón checks the page's history, whether reviewers are real, and if the price is too
                good to be true.
              </p>
            </div>

            <Button block size="lg" className="mt-auto mb-2" onClick={run} disabled={!url.trim()}>
              <Sparkles size={18} /> {t.analyzing}
            </Button>
          </motion.div>
        )}

        {phase === "analyzing" && (
          <motion.div key="analyzing" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-1 flex-col">
            <AnalysisLoader title={t.analyzing} steps={analysisSteps} activeIndex={index} percent={percent} tone="teal" />
          </motion.div>
        )}

        {phase === "report" && (
          <motion.div
            key="report"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4 px-5 pb-8 pt-2"
          >
            {/* verdict */}
            <div className={cn("relative overflow-hidden rounded-[var(--radius-lg)] p-5", rc.cls)}>
              <div className="absolute -right-6 -top-8 h-32 w-32 rounded-full bg-white/10 blur-xl" />
              <div className="relative flex items-center gap-3">
                <rc.icon size={30} />
                <div>
                  <p className="font-display text-xl font-extrabold leading-tight">{rc.label}</p>
                  <p className="truncate text-sm opacity-80">{report.handle}</p>
                </div>
              </div>
            </div>

            {/* metrics */}
            <div className="grid grid-cols-2 gap-3">
              <Metric
                icon={History}
                label={t.pageAge}
                value={
                  report.pageAgeDays > 365
                    ? `${Math.floor(report.pageAgeDays / 365)}y old`
                    : `${report.pageAgeDays}d old`
                }
                note={report.renames > 0 ? `Renamed ${report.renames}×` : "Never renamed"}
                bad={report.renames > 0 || report.pageAgeDays < 90}
              />
              <Metric
                icon={Users}
                label={t.reviewsTitle}
                value={`${report.reviewCount.toLocaleString()}`}
                note={report.reviewBurst ? "Suspicious burst" : `${report.genuineReviewers}% genuine`}
                bad={report.reviewBurst || report.genuineReviewers < 50}
              />
            </div>

            {/* price vs market */}
            {report.marketHigh > 0 && (
              <div className="rounded-[var(--radius-card)] bg-surface p-4 shadow-[var(--shadow-soft)]">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink">
                  <TrendingDown size={16} className="text-danger" /> {t.priceTitle}
                </div>
                <div className="flex items-end justify-between">
                  <div>
                    <p className="text-xs text-ink-mute">Offered</p>
                    <p className="font-display text-xl font-extrabold text-danger">
                      {formatVnd(report.priceOffered)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-ink-mute">Market</p>
                    <p className="font-display font-bold text-ink">
                      {formatVnd(report.marketLow)}–{formatVnd(report.marketHigh)}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* flags */}
            <div>
              <p className="mb-2 px-1 font-display text-[1.05rem] font-bold text-ink">
                {t.flagsTitle}
              </p>
              <div className="space-y-2">
                {report.flags.map((f, i) => {
                  const Icon = sevIcon[f.severity];
                  return (
                    <motion.div
                      key={f.label}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.15 + i * 0.07 }}
                      className="flex gap-3 rounded-2xl bg-surface p-3.5 shadow-[var(--shadow-soft)]"
                    >
                      <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-xl", sevCls[f.severity])}>
                        <Icon size={18} />
                      </span>
                      <div>
                        <p className="text-[0.92rem] font-semibold text-ink">{f.label}</p>
                        <p className="mt-0.5 text-[0.8rem] leading-snug text-ink-soft text-pretty">
                          {f.detail}
                        </p>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            </div>

            {/* advice */}
            <div className="flex items-start gap-3 rounded-[var(--radius-card)] bg-teal/8 p-4">
              <Sparkles size={18} className="mt-0.5 shrink-0 text-teal-deep" />
              <p className="text-[0.85rem] leading-snug text-ink-soft text-pretty">{report.advice}</p>
            </div>

            <Button
              variant="secondary"
              block
              onClick={() => {
                setUrl("");
                setPhase("input");
              }}
            >
              <RotateCcw size={17} /> Check another link
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </Screen>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  note,
  bad,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: string;
  note: string;
  bad?: boolean;
}) {
  return (
    <div className="rounded-[var(--radius-card)] bg-surface p-4 shadow-[var(--shadow-soft)]">
      <Icon size={18} className="text-ink-mute" />
      <p className="mt-2 text-xs font-medium text-ink-mute">{label}</p>
      <p className="font-display text-lg font-extrabold text-ink">{value}</p>
      <p className={cn("text-xs font-semibold", bad ? "text-danger" : "text-moss-strong")}>{note}</p>
    </div>
  );
}
