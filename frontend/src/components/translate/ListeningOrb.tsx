"use client";

import Image from "next/image";
import { motion } from "motion/react";

type OrbState = "idle" | "listening" | "processing";

/** The centrepiece of the voice screen — the nón lá, listening. */
export function ListeningOrb({ state }: { state: OrbState }) {
  const active = state === "listening";
  const busy = state === "processing";
  // deep-green nón in both themes
  const nonSrc = "/brand/non-dark.png";
  return (
    <div className="relative grid h-60 w-60 place-items-center">
      {/* warm glow */}
      <motion.div
        aria-hidden
        className="absolute h-48 w-48 rounded-full blur-3xl"
        style={{ background: "radial-gradient(circle, var(--color-straw) 0%, transparent 70%)" }}
        animate={{ opacity: active ? [0.55, 0.85, 0.55] : 0.4, scale: active ? [1, 1.12, 1] : 1 }}
        transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* listening ripples in straw-gold */}
      {active &&
        [0, 0.9, 1.8].map((d) => (
          <span
            key={d}
            aria-hidden
            className="absolute h-44 w-44 rounded-full border-2 border-straw/50"
            style={{ animation: `ripple 2.6s cubic-bezier(0.22,1,0.36,1) ${d}s infinite` }}
          />
        ))}

      {/* the nón */}
      <motion.div
        className="relative z-10 w-[13.5rem] drop-shadow-[0_16px_28px_rgba(30,58,52,0.28)]"
        animate={{
          y: active ? [0, -8, 0] : [0, -5, 0],
          rotate: busy ? [0, 2, -2, 0] : 0,
        }}
        transition={{
          y: { duration: active ? 2 : 5, repeat: Infinity, ease: "easeInOut" },
          rotate: { duration: 1.2, repeat: busy ? Infinity : 0, ease: "easeInOut" },
        }}
      >
        <Image src={nonSrc} alt="Nón lá" width={216} height={145} priority className="h-auto w-full" />
      </motion.div>
    </div>
  );
}

/** A live-looking equaliser used while listening (compositor-only scaleY). */
export function Waveform({ active }: { active: boolean }) {
  const bars = [10, 22, 14, 30, 18, 26, 12, 34, 20, 16, 28, 13];
  return (
    <div className="flex h-10 items-center justify-center gap-1">
      {bars.map((base, i) => (
        <motion.span
          key={i}
          className="w-1.5 rounded-full bg-straw-deep"
          style={{ height: base, transformOrigin: "center" }}
          animate={active ? { scaleY: [0.4, 1, 0.5] } : { scaleY: 0.2 }}
          transition={{
            duration: 0.7 + (i % 4) * 0.14,
            repeat: active ? Infinity : 0,
            ease: "easeInOut",
            delay: i * 0.05,
          }}
        />
      ))}
    </div>
  );
}
