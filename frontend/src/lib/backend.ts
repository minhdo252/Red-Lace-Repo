/**
 * Server-side helpers for talking to the FastAPI backend.
 *
 * Only imported by route handlers under `src/app/api/*` — never from client
 * components. The backend base URL comes from the server-only `BACKEND_URL`
 * env var so it never reaches the browser (same secret-keeping approach as the
 * SerpApi key in `api/nearby/route.ts`). When `BACKEND_URL` is unset the proxy
 * routes fall back to the app's existing mock data, so the frontend keeps
 * working before the backend is deployed.
 */

export function backendBase(): string | null {
  const raw = process.env.BACKEND_URL?.trim();
  return raw ? raw.replace(/\/+$/, "") : null;
}

/** Create a backend session and return its UUID. Throws on non-2xx. */
export async function createBackendSession(
  base: string,
  nativeLanguage: string,
  nationality: string,
): Promise<string> {
  const res = await fetch(`${base}/sessions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ native_language: nativeLanguage, nationality }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`sessions ${res.status}`);
  const json = (await res.json()) as { session_id: string };
  return json.session_id;
}

/** POST JSON to the backend with an abort timeout (chat/STT can be slow). */
export async function backendPost(
  base: string,
  path: string,
  payload: unknown,
  timeoutMs = 60000,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}
