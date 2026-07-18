import type { TourReport } from "./types";

export const analysisSteps = [
  "Opening the page",
  "Checking page history & renames",
  "Verifying reviewers are real",
  "Comparing the price to the market",
];

export const riskyTour: TourReport = {
  handle: "Halong Luxury Cruise 5★ — Super Cheap",
  platform: "Facebook",
  risk: "high",
  pageAgeDays: 23,
  renames: 3,
  reviewCount: 41,
  reviewBurst: true,
  genuineReviewers: 18,
  priceOffered: 890_000,
  marketLow: 2_400_000,
  marketHigh: 3_500_000,
  flags: [
    {
      label: "Price 63–75% below market",
      detail: "890k₫ vs a normal 2.4–3.5M₫ for a 2-day Ha Long cruise.",
      severity: "danger",
    },
    {
      label: "38 five-star reviews in 48 hours",
      detail: "A sudden burst from accounts created the same week — a classic fake-review signal.",
      severity: "danger",
    },
    {
      label: "Page renamed 3 times in 3 weeks",
      detail: "Was “Sapa Trek Deals”, then “Hanoi Food Tour”, now a cruise page.",
      severity: "warn",
    },
    {
      label: "100% deposit to a personal account",
      detail: "Legit operators rarely ask for full prepayment to an individual's bank.",
      severity: "warn",
    },
    {
      label: "No business licence listed",
      detail: "No tour-operator registration number anywhere on the page.",
      severity: "info",
    },
  ],
  advice:
    "This has multiple strong scam signals. Don't pay a deposit. Book through a licensed operator or a platform with buyer protection.",
};

export const cleanTour: TourReport = {
  handle: "Hanoi Old Quarter Free Walking Tour",
  platform: "Facebook",
  risk: "low",
  pageAgeDays: 1460,
  renames: 0,
  reviewCount: 2637,
  reviewBurst: false,
  genuineReviewers: 92,
  priceOffered: 0,
  marketLow: 0,
  marketHigh: 0,
  flags: [
    {
      label: "Established 4 years ago",
      detail: "Consistent name and steady activity since 2022.",
      severity: "info",
    },
    {
      label: "Reviews grow steadily over time",
      detail: "2,600+ reviews spread across years, from varied real accounts.",
      severity: "info",
    },
    {
      label: "Pay-what-you-want after the tour",
      detail: "No upfront deposit — you decide at the end.",
      severity: "info",
    },
  ],
  advice: "This listing looks genuine. Still, meet in a public place and keep your belongings close.",
};
