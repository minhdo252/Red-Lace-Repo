"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { Mascot } from "@/components/ui/Mascot";
import { useT } from "@/i18n";

export default function SplashPage() {
  const router = useRouter();
  const common = useT("common");

  useEffect(() => {
    const id = setTimeout(() => router.push("/onboarding"), 2400);
    return () => clearTimeout(id);
  }, [router]);

  return (
    <button
      onClick={() => router.push("/onboarding")}
      className="grain relative flex h-full w-full flex-col items-center justify-center overflow-hidden bg-[radial-gradient(120%_120%_at_50%_10%,#f1f6ef_0%,#dce8d8_55%,#c6d9c1_100%)]"
    >
      <div className="absolute -right-16 top-16 h-56 w-56 rounded-full bg-moss/15 blur-3xl" />
      <div className="absolute -left-16 bottom-24 h-56 w-56 rounded-full bg-teal/15 blur-3xl" />

      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        className="relative flex flex-col items-center"
      >
        <Mascot variant="full" size={188} float ring={false} className="drop-shadow-[0_12px_24px_rgba(30,58,52,0.18)]" />
        <div className="mt-5">
          <span className="font-display text-4xl font-extrabold tracking-tight text-forest">
            Nón<span className="text-moss">AI</span>
          </span>
        </div>
        <p className="mt-2 max-w-[22ch] text-center text-[0.9rem] font-medium text-forest/75">
          {common.tagline}
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1 }}
        className="absolute bottom-14 flex items-center gap-2 text-sm text-ink-mute"
      >
        <span className="flex gap-1">
          {[0, 0.15, 0.3].map((d) => (
            <motion.span
              key={d}
              className="h-1.5 w-1.5 rounded-full bg-moss"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 1, repeat: Infinity, delay: d }}
            />
          ))}
        </span>
      </motion.div>
    </button>
  );
}
