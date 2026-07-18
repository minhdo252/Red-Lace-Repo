import { cn } from "@/lib/utils";

type CardProps = React.HTMLAttributes<HTMLDivElement> & {
  as?: "div" | "button" | "a";
  inset?: boolean;
};

/** The base surface. Soft, rounded, single shadow — never bordered + shadowed. */
export function Card({ className, inset, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-card)] bg-surface shadow-[var(--shadow-soft)]",
        inset ? "p-4" : "",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
