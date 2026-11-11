// Minimal fetch wrapper for the local EmneKlar API.
//
// * Same-origin only; the session cookie is HttpOnly and never visible here.
// * State-changing requests carry the per-session CSRF token header.
// * Nothing secret is ever stored in localStorage/sessionStorage.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: string;
  readonly extra?: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details?: string, extra?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.extra = extra;
  }
}

let csrfToken: string | null = null;
const sessionListeners = new Set<() => void>();

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function onSessionExpired(listener: () => void): () => void {
  sessionListeners.add(listener);
  return () => {
    sessionListeners.delete(listener);
  };
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network", "Fikk ikke kontakt med EmneKlar. Kjører programmet fortsatt?");
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    const err = (
      data as { error?: { code?: string; message?: string; details?: string; extra?: Record<string, unknown> } } | null
    )?.error;
    // Only EmneKlar's own session check means the session has expired. Canvas rejecting a token is also a 401
    // (canvas_token_invalid) – that is an error to show where the token is entered, not a reason to log out.
    if (response.status === 401 && (!err?.code || err.code === "session_required")) {
      sessionListeners.forEach((listener) => listener());
    }
    throw new ApiError(
      response.status,
      err?.code ?? "internal_error",
      err?.message ?? "Noe gikk galt.",
      err?.details,
      err?.extra,
    );
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export function qs(params: Record<string, string | number | boolean | null | undefined | string[]>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
