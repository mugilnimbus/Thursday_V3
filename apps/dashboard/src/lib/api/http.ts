/* HTTP to the gateway: same origin, JSON in and out, problem+json errors as ApiError.
   Identical GETs in flight are shared, every request has a timeout, and state-changing calls carry
   the client header the gateway requires from browsers. */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
  get offline(): boolean {
    return this.status === 0;
  }
}

const TIMEOUT_MS = 20_000;
const inflight = new Map<string, Promise<unknown>>();

async function send<T>(method: string, path: string, body?: unknown, timeoutMs = TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      signal: controller.signal,
      headers: {
        'X-Thursday-Client': 'dashboard',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === 'AbortError';
    throw new ApiError(0, aborted ? 'timeout' : 'offline', aborted ? 'The request timed out.' : 'Cannot reach Thursday.');
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? safeJson(text) : undefined;
  if (!response.ok) {
    const problem = (data ?? {}) as { code?: string; detail?: string; title?: string };
    throw new ApiError(response.status, problem.code ?? 'error', problem.detail || problem.title || response.statusText);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

export function get<T>(path: string): Promise<T> {
  const existing = inflight.get(path);
  if (existing) return existing as Promise<T>;
  const request = send<T>('GET', path).finally(() => inflight.delete(path));
  inflight.set(path, request);
  return request;
}

export const post = <T>(path: string, body?: unknown, timeoutMs?: number) => send<T>('POST', path, body, timeoutMs);
export const put = <T>(path: string, body: unknown) => send<T>('PUT', path, body);
export const patch = <T>(path: string, body: unknown) => send<T>('PATCH', path, body);
export const del = <T>(path: string) => send<T>('DELETE', path);

export function query(params: Record<string, string | number | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return entries.length ? '?' + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString() : '';
}
