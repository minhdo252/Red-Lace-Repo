/**
 * Client-side API for the FastAPI backend, called through the same-origin proxy
 * routes under `src/app/api/*` (so the browser never sees the backend URL and
 * there's no CORS). Every call returns a `source: "backend" | "mock"` envelope;
 * `"mock"` means no backend is configured/reachable and the caller should use
 * its existing mock data. Also holds the locale/nationality maps and the
 * backend-response -> frontend-mock-shape mappers.
 */

import type { LocaleCode } from "@/i18n";
import type { AssistantAction, AssistantMessage, AssistantVerdict } from "@/mocks/assistant";
import type { TranslateTurn } from "@/mocks/types";

/* ---------- locale / nationality maps ---------- */

export type NativeLanguage = "vi" | "en" | "ko" | "zh" | "ja";

/** Frontend locale -> backend native_language (backend has no `ru`; use `en`). */
export function localeToNativeLanguage(locale: LocaleCode): NativeLanguage {
  switch (locale) {
    case "vi":
      return "vi";
    case "ko":
      return "ko";
    case "zh":
      return "zh";
    case "ru":
      return "en";
    default:
      return "en";
  }
}

/** Sensible default nationality (2-letter code) derived from the chosen language. */
export function localeToNationality(locale: LocaleCode): string {
  switch (locale) {
    case "ko":
      return "KR";
    case "zh":
      return "CN";
    case "ru":
      return "RU";
    case "vi":
      return "VN";
    default:
      return "US";
  }
}

/* ---------- proxy envelopes ---------- */

export type ScamFlag = {
  category?: string;
  best_score?: number;
  source?: string;
  matched_text?: string;
  top_match?: unknown;
};

export type PriceAnalysisItem = {
  item?: string | null;
  observed_price?: number | null;
  reference_price?: number | null;
  reference_price_range?: [number, number] | null;
  overpriced?: boolean;
  price_diff_pct?: number | null;
  flag?: string | null;
};

export type PriceAnalysis = {
  region?: string | null;
  items: PriceAnalysisItem[];
  overall_overpriced?: boolean;
};

export type ChatEnvelope = {
  source: "backend" | "mock";
  session_id?: string | null;
  reply?: string;
  source_text?: string | null;
  translation?: string | null;
  translation_details?: Record<string, unknown> | null;
  detected_language?: string | null;
  target_language?: string | null;
  scam_flags?: ScamFlag[];
  threat?: Record<string, unknown> | null;
  tools_invoked?: { tool?: string; arguments?: Record<string, unknown>; result?: Record<string, unknown> }[];
  normalized_prices_vnd?: number[];
  resolved_region?: string | null;
  // Input-type routing signals (backend chat-input-routing design).
  input_route?: "text" | "voice" | "image" | null;
  needs_retake?: boolean;
  retake_reason?: string | null;
  price_analysis?: PriceAnalysis | null;
  // Module 2.2 ghost-tour / URL scam-check result (real: WHOIS + Gemini web reputation).
  ghost_tour_analysis?: Record<string, unknown> | null;
  error?: string;
};

export type SessionEnvelope = { source: "backend" | "mock"; session_id?: string | null; error?: string };

export type SosContact = {
  service_type: string;
  phone_number: string;
  notes?: string | null;
  country_name?: string | null;
  address?: string | null;
  region_hint?: string | null;
  is_primary?: boolean;
  priority_rank?: number;
};

export type SosEnvelope = {
  source: "backend" | "mock";
  session_id?: string | null;
  contacts?: SosContact[];
  location_text_vi?: string | null;
  location_text_en?: string | null;
  resolved_region?: string | null;
  nationality?: string | null;
  error?: string;
};

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await res.json()) as T;
}

export function createSessionRequest(body: { native_language: string; nationality: string }) {
  return postJson<SessionEnvelope>("/api/session", body).catch(
    (e): SessionEnvelope => ({ source: "mock", session_id: null, error: String(e) }),
  );
}

export function chatRequest(body: Record<string, unknown>) {
  return postJson<ChatEnvelope>("/api/chat", body).catch(
    (e): ChatEnvelope => ({ source: "mock", error: String(e) }),
  );
}

export function sosRequest(body: Record<string, unknown>) {
  return postJson<SosEnvelope>("/api/sos", body).catch(
    (e): SosEnvelope => ({ source: "mock", error: String(e) }),
  );
}

/* ---------- file/blob -> base64 (strip the data: prefix) ---------- */

function readAsBase64(data: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(data);
  });
}

export const fileToBase64 = readAsBase64;
export const blobToBase64 = readAsBase64;

/* ---------- backend response -> frontend mock shapes ---------- */

const SCAM_LABELS: Record<string, string> = {
  price_scam: "Unusually high price",
  ghost_tour_pressure: "Pressure / ghost-tour pattern",
};

/** The price category reflects an "unusually high price", not proof of deception —
 * on its own it stays a caution and never becomes an outright "scam" verdict. */
const PRICE_CATEGORY = "price_scam";

function topScam(flags?: ScamFlag[]): ScamFlag | null {
  if (!flags || !flags.length) return null;
  return flags.reduce((a, b) => ((b.best_score ?? 0) > (a.best_score ?? 0) ? b : a));
}

/** Highest-scoring *deception* flag (ghost-tour pressure, etc.) — excludes the
 * price category, which is only ever surfaced as a caution. */
function topDeceptionScam(flags?: ScamFlag[]): ScamFlag | null {
  return topScam((flags ?? []).filter((f) => f.category !== PRICE_CATEGORY));
}

/** Was a quoted/observed price flagged above the local reference? Reads the
 * structured price_analysis (text/image/voice routes) and any price_scam flag. */
function isOverpriced(env: ChatEnvelope): boolean {
  const pa = env.price_analysis;
  if (pa?.overall_overpriced) return true;
  if (pa?.items?.some((it) => it.overpriced)) return true;
  return (env.scam_flags ?? []).some((f) => f.category === PRICE_CATEGORY);
}

/** Backend threat block -> a normalized level string. The backend emits
 * `final_level` (see app/modules/threat_detection.py); level/risk_level are kept
 * as fallbacks. */
export function threatLevel(env: ChatEnvelope): string {
  const t = env.threat as
    | { final_level?: string; level?: string; risk_level?: string }
    | null
    | undefined;
  return String(t?.final_level ?? t?.level ?? t?.risk_level ?? "NONE").toUpperCase();
}

export function isCriticalThreat(env: ChatEnvelope): boolean {
  const level = threatLevel(env);
  return level === "HIGH" || level === "CRITICAL";
}

export function verdictFor(env: ChatEnvelope): AssistantVerdict {
  if (isCriticalThreat(env)) return "scam";
  const top = topDeceptionScam(env.scam_flags);
  if (top) {
    const s = top.best_score ?? 0;
    if (s >= 0.72) return "scam";
    if (s >= 0.6) return "caution";
  }
  // A price above the local reference is a caution ("unusually high"), never an
  // outright fraud accusation — a high price alone isn't proof of a scam.
  if (isOverpriced(env)) return "caution";
  return "safe";
}

export function actionsFor(env: ChatEnvelope): AssistantAction[] {
  const actions: AssistantAction[] = [];
  if (isCriticalThreat(env)) actions.push({ label: "Emergency (SOS)", kind: "police" });
  const cats = new Set((env.scam_flags ?? []).map((f) => f.category));
  const usedTour = (env.tools_invoked ?? []).some((t) => t.tool === "check_ghost_tour");
  if (cats.has("ghost_tour_pressure") || usedTour) actions.push({ label: "Verify this operator", kind: "tour" });
  if (cats.has("price_scam") || isOverpriced(env)) actions.push({ label: "See fair-priced spots", kind: "map" });
  actions.push({ label: "Translate my reply", kind: "translate" });
  const seen = new Set<string>();
  return actions.filter((a) => {
    if (seen.has(a.kind)) return false;
    seen.add(a.kind);
    return true;
  });
}

/** Map a /chat response into the Home assistant's message shape. */
export function toAssistantMessage(env: ChatEnvelope, id: string): AssistantMessage {
  const verdict = verdictFor(env);
  const top = topScam(env.scam_flags);
  // A caution driven only by price says "price looks high" instead of the generic
  // "be careful" — we state that the price is unusually high, not that it's a scam.
  const deception = topDeceptionScam(env.scam_flags);
  const priceOnlyCaution =
    verdict === "caution" && isOverpriced(env) && (deception?.best_score ?? 0) < 0.6;
  const pattern =
    verdict === "safe" || priceOnlyCaution
      ? undefined
      : top?.category
        ? SCAM_LABELS[top.category] ?? top.category
        : undefined;
  return {
    id,
    role: "ai",
    text: env.reply || env.translation || "…",
    verdict,
    verdictLabel: priceOnlyCaution ? "Price looks high" : undefined,
    pattern,
    actions: actionsFor(env),
  };
}

/** Map a /chat response into one Translate turn (speaker = who just spoke). */
export function toTranslateTurn(env: ChatEnvelope, speakerRole: "tourist" | "vendor"): TranslateTurn {
  const d = (env.translation_details ?? {}) as Record<string, string>;
  const source = d.source_text_clean || env.source_text || "";
  const translated = d.translated_text || env.translation || "";
  // Banner text reads like the chatbot reply: drop a leading echo of the
  // translation (already shown in the bubble) so only the guidance remains.
  const rawReply = env.reply || "";
  const advice =
    (translated && rawReply.startsWith(translated) ? rawReply.slice(translated.length).trim() : rawReply) ||
    "This price looks higher than usual.";

  // Real deception (ghost-tour pressure, etc.) is a scam; a price above the local
  // reference on its own is a "price looks high" caution — same as the chatbot,
  // never an outright scam accusation.
  const deception = topDeceptionScam(env.scam_flags);
  let scam: TranslateTurn["scam"];
  if (deception?.category) {
    scam = { pattern: SCAM_LABELS[deception.category] ?? deception.category, advice, kind: "scam" };
  } else if (isOverpriced(env)) {
    scam = { pattern: "", advice, kind: "price" };
  }
  if (speakerRole === "vendor") {
    return { speaker: "them", vi: source, en: translated, scam };
  }
  return { speaker: "you", en: source, vi: translated, scam };
}
