/** The AI assistant ("Nón") — the centre of the app. */

export type AssistantVerdict = "safe" | "caution" | "scam";

export type AssistantAction = {
  label: string;
  kind: "grab" | "police" | "translate" | "price" | "tour" | "map" | "retake";
};

export type AssistantMessage = {
  id: string;
  role: "user" | "ai";
  text: string;
  image?: string; // object URL of a photo the user sent
  verdict?: AssistantVerdict;
  /** Overrides the verdict badge label (e.g. "Price looks high" for a price-only
   * caution, so we name the issue instead of the generic "Be careful"). */
  verdictLabel?: string;
  pattern?: string;
  reasons?: string[];
  actions?: AssistantAction[];
};

/** Voice/desc prompts the user can tap to demo the AI reasoning. */
export const starterPrompts: { id: string; text: string }[] = [
  { id: "p1", text: "A taxi says his meter is broken and wants 500k to Hoan Kiem" },
  { id: "p2", text: "A shop wants 90k for a bottle of water near the lake" },
  { id: "p3", text: "Someone offers a Ha Long cruise 70% off if I pay now" },
];

/** Scripted AI reply for the taxi situation (the hero demo). */
export const taxiThread: AssistantMessage[] = [
  {
    id: "u1",
    role: "user",
    text: "A taxi driver says his meter is broken and wants 500,000₫ to Hoan Kiem Lake.",
  },
  {
    id: "a1",
    role: "ai",
    text: "That has the hallmarks of a common overcharge. Here's why I'd be careful:",
    verdict: "scam",
    pattern: "“Broken meter” + inflated flat fare",
    reasons: [
      "A metered ride to Hoan Kiem from here is usually 60,000–90,000₫ — 500k is 5–7× that.",
      "“The meter is broken” is the single most-reported line before a fixed high price.",
      "Refusing the meter removes any way to verify the fare.",
    ],
    actions: [
      { label: "Book a Grab instead", kind: "grab" },
      { label: "Translate my reply", kind: "translate" },
      { label: "Tourist police", kind: "police" },
    ],
  },
];

export const waterThread: AssistantMessage[] = [
  { id: "u2", role: "user", text: "A shop wants 90,000₫ for a bottle of water near the lake." },
  {
    id: "a2",
    role: "ai",
    text: "That's high, but not necessarily a scam — tourist spots do charge more.",
    verdict: "caution",
    pattern: "Tourist-area markup",
    reasons: [
      "A 500ml bottle is normally 5,000–15,000₫ in Vietnam.",
      "90k is well above normal, but some lakeside kiosks price up for convenience.",
      "There's no deception here — you can simply decline and buy elsewhere.",
    ],
    actions: [
      { label: "Find a fair-priced shop", kind: "map" },
      { label: "Check a photo of the price", kind: "price" },
    ],
  },
];

export const cruiseThread: AssistantMessage[] = [
  { id: "u3", role: "user", text: "Someone offers a Ha Long cruise 70% off if I pay cash right now." },
  {
    id: "a3",
    role: "ai",
    text: "Please slow down — this pattern is high-risk. Do not pay yet.",
    verdict: "scam",
    pattern: "Deep discount + urgent cash-now pressure",
    reasons: [
      "70% below market for a Ha Long cruise is not sustainable for a real operator.",
      "“Pay cash now or lose it” manufactures urgency so you can't verify the company.",
      "Legitimate cruises let you book through a traceable channel and pay on confirmation.",
    ],
    actions: [
      { label: "Verify this operator", kind: "tour" },
      { label: "Translate a question for them", kind: "translate" },
    ],
  },
];

/**
 * AI-native photo scan: the user just sends a photo of a receipt/menu and Nón
 * automatically works out whether the price is fair — no "please check this" needed.
 * (Numbers mirror mocks/price-check receiptAnalysis.)
 */
export const photoScanReply: AssistantMessage = {
  id: "a-photo",
  role: "ai",
  text: "I read your receipt from the Old Quarter. Most of it is a fair tourist-area price, but a few lines are marked up more than usual.",
  verdict: "caution",
  pattern: "≈68% above the fair range for this area",
  reasons: [
    "Bún chả — you paid 240,000₫ for 2. A fair range here is 90,000–140,000₫.",
    "Trà đá (iced tea) — 40,000₫ for 2 is well over the usual 6,000–20,000₫.",
    "Whole bill: 470,000₫ vs a fair 176,000–280,000₫ for this order.",
  ],
  actions: [
    { label: "See fair-priced spots", kind: "map" },
    { label: "Translate my reply", kind: "translate" },
  ],
};

/** Pick a scripted reply from what the user typed/said (keyword-routed demo). */
export function routeThread(text: string): AssistantMessage[] {
  const q = text.toLowerCase();
  if (/(water|nước|bottle|chai)/.test(q)) return waterThread;
  if (/(cruise|tour|ha long|hạ long|du thuyền|thuyền)/.test(q)) return cruiseThread;
  return taxiThread;
}

export const threads: Record<string, AssistantMessage[]> = {
  p1: taxiThread,
  p2: waterThread,
  p3: cruiseThread,
};

export const skills: {
  key: "translate" | "price" | "tour" | "situation" | "emergency";
  href: string;
}[] = [
  { key: "situation", href: "/assistant" },
  { key: "translate", href: "/translate" },
  { key: "price", href: "/price-check" },
  { key: "tour", href: "/tour-check" },
  { key: "emergency", href: "/sos" },
];
