import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "dark";
type Size = "sm" | "md" | "lg";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  block?: boolean;
};

const variants: Record<Variant, string> = {
  primary:
    "bg-moss text-on-brand shadow-[0_10px_24px_-10px_var(--color-moss-strong)] hover:bg-moss-strong",
  secondary:
    "bg-surface text-ink border border-line hover:border-line-strong",
  ghost: "bg-transparent text-ink-soft hover:bg-black/[0.04]",
  danger:
    "bg-danger text-white shadow-[0_10px_24px_-10px_var(--color-danger)]",
  dark: "bg-white/12 text-white border border-white/15 hover:bg-white/18 backdrop-blur-md",
};

const sizes: Record<Size, string> = {
  sm: "h-10 px-4 text-sm rounded-xl",
  md: "h-12 px-5 text-[0.95rem] rounded-2xl",
  lg: "h-[3.5rem] px-6 text-base rounded-2xl",
};

export function Button({
  variant = "primary",
  size = "md",
  block,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex select-none items-center justify-center gap-2 font-semibold",
        "transition-all duration-200 ease-out active:scale-[0.97] disabled:opacity-50 disabled:pointer-events-none",
        variants[variant],
        sizes[size],
        block && "w-full",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
