import { NextResponse } from "next/server";
import { backendBase, backendPost, createBackendSession } from "@/lib/backend";

export const runtime = "nodejs";

type SosBody = {
  session_id?: string | null;
  native_language?: string;
  nationality?: string;
  lat?: number;
  lon?: number;
  region?: string;
  threat_category?: string;
  threat_level?: string;
  source?: string;
};

/**
 * POST /api/sos -> proxies to the FastAPI backend (/sos).
 *
 * Returns prioritized emergency hotlines + the embassy contact for the user's
 * nationality. Self-heals the session like /api/chat. Falls back to
 * `{ source: "mock" }` (caller uses its static hotlines) when BACKEND_URL is
 * unset or the backend errors.
 */
export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as SosBody;
  const base = backendBase();
  if (!base) return NextResponse.json({ source: "mock" });

  const nl = body.native_language ?? "en";
  const nat = body.nationality ?? "US";
  const build = (sid: string): Record<string, unknown> => ({
    session_id: sid,
    lat: body.lat,
    lon: body.lon,
    region: body.region,
    nationality: nat,
    threat_category: body.threat_category,
    threat_level: body.threat_level,
    source: body.source || "manual",
  });

  try {
    let sessionId = body.session_id || (await createBackendSession(base, nl, nat));
    let res = await backendPost(base, "/sos", build(sessionId), 30000);
    if (res.status === 404) {
      sessionId = await createBackendSession(base, nl, nat);
      res = await backendPost(base, "/sos", build(sessionId), 30000);
    }
    if (!res.ok) throw new Error(`sos ${res.status}`);
    const data = (await res.json()) as Record<string, unknown>;
    return NextResponse.json({ source: "backend", session_id: sessionId, ...data });
  } catch (error) {
    return NextResponse.json({
      source: "mock",
      error: error instanceof Error ? error.message : "unknown",
    });
  }
}
