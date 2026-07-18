import clsx, { type ClassValue } from "clsx";

/** Merge conditional class names. */
export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

/** Promise-based delay for mock "network" latency. */
export function delay(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

/** Format seconds as m:ss (or h:mm:ss). */
export function formatDuration(totalSeconds: number) {
  const s = Math.floor(totalSeconds % 60);
  const m = Math.floor((totalSeconds / 60) % 60);
  const h = Math.floor(totalSeconds / 3600);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** Format a VND amount with thousands separators. */
export function formatVnd(amount: number) {
  return new Intl.NumberFormat("vi-VN").format(amount) + "₫";
}
