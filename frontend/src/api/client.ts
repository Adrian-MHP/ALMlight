// Minimal fetch wrapper for the ALMlight API. The session lives in an httpOnly cookie.

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Human-readable message including field errors and blocking reasons. */
  get full(): string {
    const parts = [this.message];
    const fields = this.details.fields as Record<string, string> | undefined;
    if (fields) parts.push(...Object.values(fields));
    const blocked = this.details.blocked_by as string[] | undefined;
    if (blocked) parts.push(...blocked);
    const problems = this.details.problems as string[] | undefined;
    if (problems) parts.push(...problems);
    const errors = this.details.errors as { loc?: unknown[]; msg?: string }[] | undefined;
    if (errors) parts.push(...errors.map((e) => `${(e.loc ?? []).join(".")}: ${e.msg}`));
    return parts.join(" — ");
  }
}

const BASE = "/api/v1";

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) {
    const ctype = res.headers.get("content-type") ?? "";
    return (ctype.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
  }
  let code = "error";
  let message = `${res.status} ${res.statusText}`;
  let details: Record<string, unknown> = {};
  try {
    const body = await res.json();
    if (body?.error) {
      code = body.error.code;
      message = body.error.message;
      details = body.error.details ?? {};
    }
  } catch {
    /* not JSON */
  }
  throw new ApiError(res.status, code, message, details);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return handle<T>(res);
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: async <T>(path: string, form: FormData): Promise<T> =>
    handle<T>(await fetch(BASE + path, { method: "POST", credentials: "same-origin", body: form })),
};

export function qs(params: Record<string, string | number | boolean | string[] | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** URL for file downloads (handled by the browser with the session cookie). */
export function downloadUrl(path: string): string {
  return BASE + path;
}
