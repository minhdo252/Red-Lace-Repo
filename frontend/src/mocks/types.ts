/**
 * Mock data shapes — deliberately written to look like future API responses.
 * When the backend is ready, `mocks/api.ts` is the only file that changes.
 */

export type Verdict = "fair" | "mid" | "high";
export type Risk = "low" | "medium" | "high";

export type PriceItem = {
  name: string;
  qty: number;
  paid: number; // VND
  refLow: number;
  refHigh: number;
  verdict: Verdict;
};

export type PriceAnalysis = {
  area: string;
  currency: "VND";
  totalPaid: number;
  refLow: number;
  refHigh: number;
  verdict: Verdict;
  overpayPct: number; // % above the fair top, 0 if fair
  items: PriceItem[];
};

export type TranslateTurn = {
  speaker: "you" | "them";
  en: string; // English (what the tourist reads)
  vi: string; // Vietnamese (what the vendor reads)
  scam?: {
    pattern: string;
    advice: string;
    /** "price" = an unusually high price (a caution — not fraud); "scam" = a real
     * deception pattern. Absent defaults to "scam" (legacy/mock turns). */
    kind?: "scam" | "price";
  };
};

export type TourFlag = {
  label: string;
  detail: string;
  severity: "info" | "warn" | "danger";
};

export type TourReport = {
  handle: string;
  platform: "Facebook" | "Website" | "Instagram";
  risk: Risk;
  pageAgeDays: number;
  renames: number;
  reviewCount: number;
  reviewBurst: boolean; // many reviews in a short window
  genuineReviewers: number; // %
  priceOffered: number;
  marketLow: number;
  marketHigh: number;
  flags: TourFlag[];
  advice: string;
};

export type MapPlace = {
  id: string;
  name: string;
  kind: "police" | "hospital" | "trusted" | "embassy";
  distance: string;
  x: number; // % position on the mock map
  y: number;
  note?: string;
};

export type ActivityItem = {
  id: string;
  kind: "price" | "tour" | "translate" | "sos";
  title: string;
  subtitle: string;
  time: string;
  verdict?: Verdict | Risk | "safe";
};

export type SafetyTip = {
  id: string;
  title: string;
  body: string;
  tone: "info" | "warn";
};

export type NearbyPlace = {
  id: string;
  name: string;
  category: string;
  priceLevel: string;
  rating: number;
  image: string;
};
