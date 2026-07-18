"use client";

import { AnimatePresence, motion } from "motion/react";
import { Sun, Moon } from "lucide-react";
import { useApp } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * Light/dark switch.
 * `compact` = round icon button (top bars). Otherwise a labelled pill (drawer / settings).
 */
export function ThemeToggle({
  compact,
  className,
}: {
  compact?: boolean;
  className?: string;
}) {
  const { theme, toggleTheme } = useApp();
  const isDark = theme === "dark";

  const icon = (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={theme}
        initial={{ rotate: -90, opacity: 0, scale: 0.6 }}
        animate={{ rotate: 0, opacity: 1, scale: 1 }}
        exit={{ rotate: 90, opacity: 0, scale: 0.6 }}
        transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
        className="grid place-items-center"
      >
        {isDark ? <Moon size={compact ? 19 : 18} /> : <Sun size={compact ? 20 : 18} />}
      </motion.span>
    </AnimatePresence>
  );

  if (compact) {
    return (
      <button
        onClick={toggleTheme}
        aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        className={cn(
          "grid h-10 w-10 place-items-center rounded-full bg-surface text-ink-soft shadow-[var(--shadow-soft)] active:scale-95",
          className,
        )}
      >
        {icon}
      </button>
    );
  }

  return (
    <button
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className={cn(
        "flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors active:bg-surface-2",
        className,
      )}
    >
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-surface-2 text-ink-soft">
        {icon}
      </span>
      <span className="flex-1 font-medium text-ink">{isDark ? "Dark mode" : "Light mode"}</span>
      <span
        className={cn(
          "relative h-6 w-11 rounded-full transition-colors",
          isDark ? "bg-teal-deep" : "bg-line-strong",
        )}
      >
        <motion.span
          layout
          transition={{ type: "spring", stiffness: 500, damping: 34 }}
          className={cn(
            "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm",
            isDark ? "right-0.5" : "left-0.5",
          )}
        />
      </span>
    </button>
  );
}
