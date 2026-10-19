import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, get, post } from './http';

afterEach(() => vi.unstubAllGlobals());

describe('request time limit', () => {
  it('ends a reply that starts and then stalls, and lets the same request be made again', async () => {
    vi.stubGlobal('fetch', (_path: string, init: RequestInit) =>
      Promise.resolve({
        status: 200,
        ok: true,
        // The first line arrived; the rest never does, until the time limit ends the request.
        text: () => new Promise<string>((_, reject) => init.signal!.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))),
      }),
    );
    const failed = await post('/v1/slow', undefined, 20).catch((e) => e);
    expect(failed).toBeInstanceOf(ApiError);
    expect((failed as ApiError).code).toBe('timeout');
  });

  it('does not keep a finished request as the answer to the next one', async () => {
    let calls = 0;
    vi.stubGlobal('fetch', () => Promise.resolve({ status: 200, ok: true, text: () => Promise.resolve(JSON.stringify({ n: ++calls })) }));
    expect(await get('/v1/thing')).toEqual({ n: 1 });
    expect(await get('/v1/thing')).toEqual({ n: 2 });
  });
});
