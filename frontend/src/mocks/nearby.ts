/** A place shown in the "Nearby" recommendations — shape returned by /api/nearby. */
export type NearbyPlace = {
  id: string;
  name: string;
  category: string;
  rating?: number;
  reviews?: number;
  address?: string;
  photo?: string; // image URL (Google-hosted when live, local when mock)
  lat?: number;
  lng?: number;
};

export type NearbyResponse = {
  source: "serpapi" | "mock";
  places: NearbyPlace[];
  error?: string;
};

/** Search presets (filter chips) → the query sent to Google Maps via SerpApi. */
export const nearbyFilters: { key: string; label: string; q: string }[] = [
  { key: "food", label: "Food", q: "restaurants" },
  { key: "cafe", label: "Cafés", q: "coffee shops cafe" },
  { key: "atm", label: "ATM", q: "atm bank" },
  { key: "police", label: "Police", q: "police station" },
  { key: "hospital", label: "Hospital", q: "hospital clinic" },
  { key: "pharmacy", label: "Pharmacy", q: "pharmacy" },
];

/**
 * Curated fallback (Old Quarter, Hà Nội) — shown only when SERPAPI_KEY is
 * missing or the monthly quota is exhausted, so the demo never breaks.
 */
export const fallbackNearby: NearbyPlace[] = [
  {
    id: "f1",
    name: "Phở Gia Truyền Bát Đàn",
    category: "Vietnamese restaurant",
    rating: 4.5,
    reviews: 8200,
    address: "49 Bát Đàn, Hoàn Kiếm",
    photo: "/content/hanoi.jpg",
    lat: 21.0325,
    lng: 105.8487,
  },
  {
    id: "f2",
    name: "Cộng Cà Phê — Nhà Thờ",
    category: "Coffee shop",
    rating: 4.4,
    reviews: 5100,
    address: "27 Nhà Thờ, Hoàn Kiếm",
    photo: "/content/lotus.jpg",
    lat: 21.0288,
    lng: 105.8492,
  },
  {
    id: "f3",
    name: "Bún Chả Hương Liên",
    category: "Vietnamese restaurant",
    rating: 4.2,
    reviews: 6400,
    address: "24 Lê Văn Hưu, Hai Bà Trưng",
    photo: "/content/countryside.jpg",
    lat: 21.0189,
    lng: 105.8524,
  },
  {
    id: "f4",
    name: "Hoàn Kiếm District Police",
    category: "Police station",
    rating: 4.0,
    reviews: 210,
    address: "2 Tràng Thi, Hoàn Kiếm",
    photo: "/content/hanoi.jpg",
    lat: 21.0301,
    lng: 105.8516,
  },
  {
    id: "f5",
    name: "Hồng Ngọc General Hospital",
    category: "Hospital",
    rating: 4.1,
    reviews: 1300,
    address: "55 Yên Ninh, Ba Đình",
    photo: "/content/lotus.jpg",
    lat: 21.0412,
    lng: 105.8442,
  },
  {
    id: "f6",
    name: "Highlands Coffee — Hàm Cá Mập",
    category: "Coffee shop",
    rating: 4.3,
    reviews: 9800,
    address: "7 Đinh Tiên Hoàng, Hoàn Kiếm",
    photo: "/content/countryside.jpg",
    lat: 21.0308,
    lng: 105.8547,
  },
];
