import { NextResponse } from "next/server";
import { backendBase, createBackendSession } from "@/lib/backend";

export const runtime = "nodejs";

/**
 * POST /api/session  { native_language, nationality } -> { source, session_id }
 *
 * Creates (or returns null for) a backend onboarding session. The client stores
 * the returned `session_id` and sends it with every /api/chat and /api/sos call.
 * With no BACKEND_URL configured, returns `session_id: null` so the app runs on
 * mock data.
 */
export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    native_language?: string;
    nationality?: string;
  };
  const base = backendBase();
  if (!base) return NextResponse.json({ source: "mock", session_id: null });

  try {
    const sessionId = await createBackendSession(
      base,
      body.native_language ?? "en",
      body.nationality ?? "US",
    );
    return NextResponse.json({ source: "backend", session_id: sessionId });
  } catch (error) {
    return NextResponse.json({
      source: "mock",
      session_id: null,
      error: error instanceof Error ? error.message : "unknown",
    });
  }
}
