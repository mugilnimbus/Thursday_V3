/* Turn metrics samples into what Monitor shows. Pure, so it is unit tested. */

import type { MetricsSample, ServiceSample } from '../../lib/api/types';

export type Hue = 'calm' | 'info' | 'warm' | 'alert' | 'focus';

export const SERVICE_LABEL: Record<string, string> = {
  gateway: 'Gateway',
  voice_agent: 'Voice agent',
  main_agent: 'Main agent',
};

/** What the stored data of each service holds, in a few words. */
export const STORAGE_LABEL: Record<string, string> = {
  gateway: 'Gateway · chats and events',
  main_agent: 'Main agent · tasks and saved steps',
  voice_agent: 'Voice agent · conversations',
  tool_server: 'Tool server · call logs',
  logs: 'Log files',
};

/** A size as people read it: 154 MB, 1.2 GB. */
export function bytesText(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return bytes >= 1e3 ? `${Math.round(bytes / 1e3)} kB` : `${bytes} B`;
}

/** Each service's stored data and the total, or null when the collector has not measured it. */
export function storedData(sample: MetricsSample | null): { total: number; parts: { label: string; bytes: number }[] } | null {
  const storage = sample?.storage ?? [];
  if (!storage.length) return null;
  return { total: storage.reduce((n, s) => n + s.bytes, 0), parts: storage.map((s) => ({ label: STORAGE_LABEL[s.name] ?? s.name, bytes: s.bytes })) };
}

export function service(sample: MetricsSample | null, name: string): ServiceSample | undefined {
  return sample?.services.find((s) => s.name === name);
}

export function num(sample: MetricsSample | null, name: string, key: string): number | null {
  const v = service(sample, name)?.metrics[key];
  return typeof v === 'number' ? v : null;
}

export function hueFor(fraction: number): Hue {
  if (fraction >= 0.9) return 'alert';
  if (fraction >= 0.75) return 'warm';
  return 'calm';
}

export function gpuMemory(sample: MetricsSample | null): { used: number; total: number } {
  const gpus = sample?.gpus ?? [];
  return { used: gpus.reduce((n, g) => n + g.vram_used_mb, 0), total: gpus.reduce((n, g) => n + g.vram_total_mb, 0) };
}

export function gb(mb: number): string {
  return (mb / 1024).toFixed(mb >= 10_240 ? 0 : 1);
}

export function rate(bytesPerSecond: number): string {
  if (bytesPerSecond >= 1_048_576) return `${(bytesPerSecond / 1_048_576).toFixed(1)} MB/s`;
  if (bytesPerSecond >= 1024) return `${Math.round(bytesPerSecond / 1024)} kB/s`;
  return `${Math.round(bytesPerSecond)} B/s`;
}

/** The one-sentence story at the top of Monitor: what is down, then what is nearly full. */
export function headline(sample: MetricsSample | null, now = Date.now()): { text: string; alert: string | null } {
  if (!sample) return { text: 'No measurements yet. The metrics collector may not be running.', alert: null };
  if (now - Date.parse(sample.ts) > 30_000) return { text: 'Measurements stopped arriving. The metrics collector may have stopped.', alert: null };
  const down = sample.services.filter((s) => !s.up).map((s) => SERVICE_LABEL[s.name] ?? s.name);
  const text = down.length ? `${down.join(' and ')} ${down.length > 1 ? 'are' : 'is'} not running.` : 'Everything is running.';
  const vram = gpuMemory(sample);
  if (vram.total && vram.used / vram.total >= 0.85)
    return { text, alert: 'GPU memory is nearly full, so a larger context will not fit until a model is unloaded.' };
  if (sample.ram_total_mb && sample.ram_used_mb / sample.ram_total_mb >= 0.9) return { text, alert: 'RAM is nearly full.' };
  return { text, alert: null };
}
