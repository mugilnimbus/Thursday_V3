/* Visibility-aware polling (the design system's live.js rules).

   One loop per resource, at most one request in flight, the next poll scheduled after the current
   one finishes, paused while the tab is hidden or offline, jittered backoff on errors, and a
   refresh on return. A response that arrives after a newer one started is dropped. */

export interface PollOptions<T> {
  fetch: () => Promise<T>;
  onData: (data: T) => void;
  onError?: (error: unknown) => void;
  intervalMs: number;
  maxBackoffMs?: number;
}

export class Poller<T> {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private inFlight = false;
  private generation = 0;
  private failures = 0;
  private readonly onVisibility = () => (document.hidden ? this.pause() : this.refresh());
  private readonly onOnline = () => this.refresh();

  constructor(private readonly opts: PollOptions<T>) {}

  start(): () => void {
    this.running = true;
    document.addEventListener('visibilitychange', this.onVisibility);
    window.addEventListener('online', this.onOnline);
    this.refresh();
    return () => this.stop();
  }

  stop(): void {
    this.running = false;
    this.pause();
    document.removeEventListener('visibilitychange', this.onVisibility);
    window.removeEventListener('online', this.onOnline);
  }

  /** Poll now (for example after a user action), then continue on the interval. */
  refresh(): void {
    if (!this.running || document.hidden) return;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    void this.tick();
  }

  private pause(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.generation += 1; // results of requests still in flight are ignored
  }

  private async tick(): Promise<void> {
    if (this.inFlight) return;
    this.inFlight = true;
    const generation = ++this.generation;
    try {
      const data = await this.opts.fetch();
      if (generation !== this.generation) return;
      this.failures = 0;
      this.opts.onData(data);
    } catch (error) {
      if (generation !== this.generation) return;
      this.failures += 1;
      this.opts.onError?.(error);
    } finally {
      this.inFlight = false;
      if (this.running && !document.hidden && generation === this.generation) this.schedule();
    }
  }

  private schedule(): void {
    const backoff = this.failures
      ? Math.min(this.opts.maxBackoffMs ?? 60_000, this.opts.intervalMs * 2 ** this.failures)
      : this.opts.intervalMs;
    const jitter = backoff * (0.9 + Math.random() * 0.2);
    this.timer = setTimeout(() => void this.tick(), jitter);
  }
}
