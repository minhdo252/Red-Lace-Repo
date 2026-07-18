"use client";

import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";

export function BottomSheet({
  open,
  onClose,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute inset-0 z-40 flex items-end"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.button
            aria-label="Close"
            onClick={onClose}
            className="absolute inset-0 bg-forest-deep/40 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <motion.div
            className={cn(
              "relative z-10 w-full rounded-t-[1.75rem] bg-surface p-5 pb-[calc(env(safe-area-inset-bottom)+1.25rem)] shadow-[0_-12px_40px_-16px_rgba(20,40,34,0.4)]",
              className,
            )}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 320 }}
          >
            <div className="mx-auto mb-4 h-1.5 w-10 rounded-full bg-line-strong" />
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
