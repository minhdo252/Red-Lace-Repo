import { NextResponse } from "next/server";
import { backendBase, backendPost, createBackendSession } from "@/lib/backend";

export const runtime = "nodejs";

type ImagePayload = { image_base64: string; mode: string };
type HistoryMessage = { role: "user" | "assistant"; content: string };

type ChatBody = {
  session_id?: string | null;
  native_language?: string;
  nationality?: string;
  text?: string;
  audio_base64?: string;
  audio_format?: string;
  images?: ImagePayload[];
  speaker_role?: string;
  lat?: number;
  lon?: number;
  region?: string;
  history?: HistoryMessage[];
};

/**
 * POST /api/chat -> proxies to the FastAPI backend (/chat or /chat/text).
 *
 * Handles text, voice (audio_base64), and image attachments in one route.
 * Self-heals: if the backend rejects the session (404), it creates a fresh one
 * from native_language + nationality and retries once, returning the new
 * session_id so the client can update its stored id. Falls back to
 * `{ source: "mock" }` when BACKEND_URL is unset or the backend errors, so the
 * caller can use its existing mock reply.
 */
export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as ChatBody;
  const base = backendBase();
  if (!base) return NextResponse.json({ source: "mock" });

  const hasAudio = !!body.audio_base64;
  const images = Array.isArray(body.images) ? body.images : [];
  const hasImages = images.length > 0;
  // The backend requires exactly one of text / audio; give an image-only turn a
  // default caption so the vision read has something to attach to.
  const text =
    body.text && body.text.trim()
      ? body.text
      : hasImages && !hasAudio
        ? "Xem giúp tôi ảnh này."
        : (body.text ?? "");

  const common = {
    speaker_role: body.speaker_role,
    lat: body.lat,
    lon: body.lon,
    region: body.region,
    history: body.history ?? [],
  };

  const build = (sid: string): { path: string; payload: Record<string, unknown> } => {
    if (hasAudio) {
      return {
        path: "/chat",
        payload: {
          session_id: sid,
          audio_base64: body.audio_base64,
          audio_format: body.audio_format || "webm",
          images,
          ...common,
        },
      };
    }
    if (hasImages) {
      return { path: "/chat", payload: { session_id: sid, text, images, ...common } };
    }
    return { path: "/chat/text", payload: { session_id: sid, text, ...common } };
  };

  const nl = body.native_language ?? "en";
  const nat = body.nationality ?? "US";

  try {
    let sessionId = body.session_id || (await createBackendSession(base, nl, nat));
    let { path, payload } = build(sessionId);
    let res = await backendPost(base, path, payload);
    if (res.status === 404) {
      sessionId = await createBackendSession(base, nl, nat);
      ({ path, payload } = build(sessionId));
      res = await backendPost(base, path, payload);
    }
    if (!res.ok) throw new Error(`chat ${res.status}`);
    const data = (await res.json()) as Record<string, unknown>;
    return NextResponse.json({ source: "backend", session_id: sessionId, ...data });
  } catch (error) {
    return NextResponse.json({
      source: "mock",
      error: error instanceof Error ? error.message : "unknown",
    });
  }
}
