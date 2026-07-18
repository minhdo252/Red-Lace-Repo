import { cn } from "@/lib/utils";

type ChipProps = React.HTMLAttributes<HTMLSpanElement> & {
  tone?: "neutral" | "moss" | "teal" | "straw" | "fair" | "mid" | "high";
  size?: "sm" | "md";
};

const tones = {
  neutral: "bg-surface-2 text-ink-soft",
  moss: "bg-moss-soft text-moss-strong",
  teal: "bg-teal/15 text-teal-deep",
  straw: "bg-straw/20 text-straw-deep",
  fair: "bg-fair/12 text-fair",
  mid: "bg-mid/18 text-[oklch(0.5_0.12_70)]",
  high: "bg-high/12 text-high",
} as const;

export function Chip({
  tone = "neutral",
  size = "md",
  className,
  children,
  ...props
}: ChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-semibold",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-[0.8rem]",
        tones[tone],
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}
