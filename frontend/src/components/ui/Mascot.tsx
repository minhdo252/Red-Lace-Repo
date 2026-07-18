import Image from "next/image";
import { cn } from "@/lib/utils";

/** The official mascot. `face` = square avatar crop, `full` = whole figure. */
export function Mascot({
  variant = "face",
  size = 56,
  className,
  ring,
  float,
}: {
  variant?: "face" | "full";
  size?: number;
  className?: string;
  ring?: boolean;
  float?: boolean;
}) {
  const src = variant === "face" ? "/brand/mascot-face-v2.png" : "/brand/mascot-v2.png";
  const isFace = variant === "face";
  return (
    <div
      className={cn(
        isFace && "overflow-hidden rounded-full bg-straw/15",
        ring && "ring-2 ring-white shadow-[var(--shadow-soft)]",
        float && "animate-float",
        className,
      )}
      style={isFace ? { width: size, height: size } : { width: size }}
    >
      <Image
        src={src}
        alt="Nón, your travel guide"
        width={isFace ? size : size}
        height={isFace ? size : Math.round(size * 1.178)}
        priority
        className={cn(isFace ? "h-full w-full object-cover" : "h-auto w-full")}
      />
    </div>
  );
}
