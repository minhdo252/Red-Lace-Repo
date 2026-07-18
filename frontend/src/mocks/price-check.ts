import type { PriceAnalysis } from "./types";

/** A bún chả lunch in a tourist-heavy street — noticeably above local rates. */
export const receiptAnalysis: PriceAnalysis = {
  area: "Old Quarter, Hà Nội",
  currency: "VND",
  totalPaid: 470_000,
  refLow: 176_000,
  refHigh: 280_000,
  verdict: "high",
  overpayPct: 68,
  items: [
    { name: "Bún chả", qty: 2, paid: 240_000, refLow: 90_000, refHigh: 140_000, verdict: "high" },
    { name: "Nem rán (spring rolls)", qty: 1, paid: 90_000, refLow: 40_000, refHigh: 60_000, verdict: "mid" },
    { name: "Trà đá (iced tea)", qty: 2, paid: 40_000, refLow: 6_000, refHigh: 20_000, verdict: "high" },
    { name: "Bia Hà Nội", qty: 2, paid: 100_000, refLow: 40_000, refHigh: 60_000, verdict: "mid" },
  ],
};

export const analysisSteps = [
  "Reading the receipt",
  "Matching items to local menus",
  "Comparing with this area's prices",
  "Estimating a fair range",
];
