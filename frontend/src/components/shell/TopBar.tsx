"use client";

import { useRouter } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";

/** Compact top bar for module screens, with an optional back button. */
export function TopBar({
  title,
  subtitle,
  back = true,
  tone = "light",
  right,
  onBack,
}: {
  title?: string;
  subtitle?: string;
  back?: boolean;
  tone?: "light" | "dark";
  right?: React.ReactNode;
  onBack?: () => void;
}) {
  const router = useRouter();
  const dark = tone === "dark";

  return (
    <div className="flex items-center gap-3 px-4 pb-2 pt-2">
      {back && (
        <button
          onClick={onBack ?? (() => router.back())}
          aria-label="Back"
          className={cn(
            "grid h-10 w-10 shrink-0 place-items-center rounded-full transition-colors active:scale-95",
            dark ? "bg-white/12 text-white" : "bg-surface text-ink shadow-[var(--shadow-soft)]",
          )}
        >
          <ChevronLeft size={22} />
        </button>
      )}
      <div className="min-w-0 flex-1">
        {title && (
          <h1
            className={cn(
              "truncate font-display text-lg font-bold leading-tight",
              dark ? "text-white" : "text-ink",
            )}
          >
            {title}
          </h1>
        )}
        {subtitle && (
          <p className={cn("truncate text-xs", dark ? "text-white/60" : "text-ink-mute")}>
            {subtitle}
          </p>
        )}
      </div>
      {right}
    </div>
  );
}
