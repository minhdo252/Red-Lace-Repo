import Image from "next/image";
import { cn } from "@/lib/utils";

/** The official nón lá logomark. */
export function Logo({
  size = 32,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <Image
      src="/brand/logomark.svg"
      alt="NónAI"
      width={size}
      height={size}
      priority
      className={className}
    />
  );
}

/** Mark + wordmark lockup. */
export function LogoLockup({
  size = 32,
  className,
  tone = "ink",
}: {
  size?: number;
  className?: string;
  tone?: "ink" | "light";
}) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Logo size={size} />
      <span
        className={cn(
          "font-display text-[1.35rem] font-extrabold leading-none tracking-tight",
          tone === "light" ? "text-white" : "text-ink",
        )}
      >
        Nón<span className="text-moss">AI</span>
      </span>
    </div>
  );
}
