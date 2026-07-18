import { cn } from "@/lib/utils";

type ScreenProps = {
  children: React.ReactNode;
  variant?: "light" | "dark";
  /** Add bottom padding so content clears a bottom nav / action bar. */
  withNav?: boolean;
  className?: string;
  /** Extra classes for the scrolling inner container. */
  scrollClassName?: string;
};

/**
 * A full-height scroll container that respects the phone's safe areas.
 * `variant="dark"` flips design tokens (forest theme) for AI / voice / SOS.
 */
export function Screen({
  children,
  variant = "light",
  withNav = false,
  className,
  scrollClassName,
}: ScreenProps) {
  return (
    <div
      data-theme={variant === "dark" ? "dark" : undefined}
      className={cn(
        "relative flex h-full min-h-0 flex-1 flex-col bg-bg text-ink",
        variant === "dark" &&
          "bg-[radial-gradient(130%_100%_at_50%_-10%,#20463c_0%,#16302a_45%,#0f231d_100%)]",
        className,
      )}
    >
      <div
        className={cn(
          "scroll-area no-scrollbar relative flex-1 overflow-y-auto overflow-x-hidden",
          "pt-[max(env(safe-area-inset-top),0.5rem)]",
          withNav
            ? "pb-[calc(env(safe-area-inset-bottom)+6.5rem)]"
            : "pb-[max(env(safe-area-inset-bottom),1rem)]",
          scrollClassName,
        )}
      >
        {children}
      </div>
    </div>
  );
}
