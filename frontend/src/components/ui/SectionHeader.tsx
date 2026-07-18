import { cn } from "@/lib/utils";

export function SectionHeader({
  title,
  action,
  onAction,
  className,
}: {
  title: string;
  action?: string;
  onAction?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-baseline justify-between px-1", className)}>
      <h2 className="font-display text-[1.05rem] font-bold text-ink">{title}</h2>
      {action && (
        <button
          onClick={onAction}
          className="text-sm font-semibold text-moss-strong active:opacity-60"
        >
          {action}
        </button>
      )}
    </div>
  );
}
