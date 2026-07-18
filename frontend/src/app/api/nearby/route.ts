import { NextResponse } from "next/server";
import { fallbackNearby, type NearbyPlace, type NearbyResponse } from "@/mocks/nearby";

export const runtime = "nodejs";

/** Minimal shape of a SerpApi google_maps local result (only the fields we use). */
interface SerpLocalResult {
  place_id?: string;
  title?: string;
  type?: string;
  rating?: number;
  reviews?: number;
  address?: string;
  thumbnail?: string;
  gps_coordinates?: { latitude?: number; longitude?: number };
}

const HOAN_KIEM = { lat: "21.0287", lng: "105.8524" };

/**
 * Backend for the map screen. Calls Google Maps (via SerpApi) server-side so the
 * key stays secret and there's no CORS. Cached 10 min per query to protect the
 * free-tier quota; falls back to curated data if the key is missing or quota runs out.
 *
 * GET /api/nearby?lat=&lng=&q=restaurants
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const lat = searchParams.get("lat") || HOAN_KIEM.lat;
  const lng = searchParams.get("lng") || HOAN_KIEM.lng;
  const q = searchParams.get("q") || "restaurants and cafes";
  const key = process.env.SERPAPI_KEY;

  if (!key) {
    return NextResponse.json({ source: "mock", places: fallbackNearby } satisfies NearbyResponse);
  }

  try {
    const url =
      `https://serpapi.com/search.json?engine=google_maps&type=search` +
      `&q=${encodeURIComponent(q)}&ll=@${lat},${lng},15z&hl=en&api_key=${key}`;

    // Cache identical queries for 10 minutes to conserve the 250/month quota.
    const res = await fetch(url, { next: { revalidate: 600 } });
    if (!res.ok) throw new Error(`serpapi responded ${res.status}`);

    const data: { local_results?: SerpLocalResult[] } = await res.json();
    const results = Array.isArray(data.local_results) ? data.local_results : [];

    const places: NearbyPlace[] = results
      .slice(0, 14)
      .filter((r) => r.title)
      .map((r, i) => ({
        id: r.place_id || `r-${i}`,
        name: r.title as string,
        category: r.type || "Place",
        rating: r.rating,
        reviews: r.reviews,
        address: r.address,
        photo: r.thumbnail,
        lat: r.gps_coordinates?.latitude,
        lng: r.gps_coordinates?.longitude,
      }));

    if (!places.length) throw new Error("no results");

    return NextResponse.json({ source: "serpapi", places } satisfies NearbyResponse);
  } catch (error) {
    // Graceful degradation — never let the demo break.
    return NextResponse.json({
      source: "mock",
      places: fallbackNearby,
      error: error instanceof Error ? error.message : "unknown",
    } satisfies NearbyResponse);
  }
}
