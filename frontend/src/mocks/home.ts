import type { ActivityItem, NearbyPlace, SafetyTip } from "./types";

export const safetyTips: SafetyTip[] = [
  {
    id: "t1",
    title: "Taxi from the Old Quarter",
    body: "Metered fare to the airport is about 250–320k₫. Agree on the meter before you go.",
    tone: "info",
  },
  {
    id: "t2",
    title: "Watch the “broken meter” line",
    body: "If a driver says the meter is broken and quotes a flat 500k₫, step out and book Grab.",
    tone: "warn",
  },
];

export const nearby: NearbyPlace[] = [
  {
    id: "n1",
    name: "Phở Gia Truyền",
    category: "Phở · Hàng Bồ",
    priceLevel: "45–60k₫",
    rating: 4.8,
    image: "/content/hanoi.jpg",
  },
  {
    id: "n2",
    name: "Cộng Cà Phê",
    category: "Coffee · Hoàn Kiếm",
    priceLevel: "35–55k₫",
    rating: 4.7,
    image: "/content/lotus.jpg",
  },
  {
    id: "n3",
    name: "Chả Cá Thăng Long",
    category: "Seafood · Old Quarter",
    priceLevel: "170–220k₫",
    rating: 4.6,
    image: "/content/countryside.jpg",
  },
];

export const recentActivity: ActivityItem[] = [
  {
    id: "a1",
    kind: "price",
    title: "Bún chả receipt",
    subtitle: "Chợ Đồng Xuân · fair price",
    time: "2h ago",
    verdict: "fair",
  },
  {
    id: "a2",
    kind: "tour",
    title: "Ha Long 2D1N tour",
    subtitle: "facebook.com/halong… · high risk",
    time: "Yesterday",
    verdict: "high",
  },
  {
    id: "a3",
    kind: "translate",
    title: "Cyclo ride negotiation",
    subtitle: "Translated · flagged 1 scam",
    time: "Yesterday",
    verdict: "safe",
  },
];
