import { describe, expect, it } from 'vitest';
import type { MetricsSample } from '../../lib/api/types';
import { gb, headline, hueFor, num, rate } from './monitor';

const NOW = Date.parse('2026-10-01T12:00:00Z');

function sample(over: Partial<MetricsSample> = {}): MetricsSample {
  return {
    ts: new Date(NOW - 2000).toISOString(),
    cpu_percent: 14,
    ram_used_mb: 30_000,
    ram_total_mb: 65_536,
    net_rx_bytes_per_s: 0,
    net_tx_bytes_per_s: 0,
    gpus: [{ index: 0, name: 'RTX', vram_used_mb: 4000, vram_total_mb: 12_288, util_percent: 10 }],
    services: [
      { name: 'gateway', up: true, latency_ms: 2, metrics: { queued_messages: 0 } },
      { name: 'main_agent', up: true, latency_ms: 4, metrics: { llm_tokens_per_second: 104.2 } },
      { name: 'voice_agent', up: true, latency_ms: 3, metrics: {} },
    ],
    ...over,
  };
}

describe('monitor story', () => {
  it('says everything runs when it does', () => {
    expect(headline(sample(), NOW)).toEqual({ text: 'Everything is running.', alert: null });
  });

  it('names what is down and warns about full GPU memory', () => {
    const s = sample({
      gpus: [{ index: 0, name: 'RTX', vram_used_mb: 11_500, vram_total_mb: 12_288, util_percent: 90 }],
      services: [{ name: 'voice_agent', up: false, latency_ms: null, metrics: {} }],
    });
    const story = headline(s, NOW);
    expect(story.text).toBe('Voice agent is not running.');
    expect(story.alert).toContain('GPU memory is nearly full');
  });

  it('notices when samples stop', () => {
    expect(headline(sample({ ts: new Date(NOW - 60_000).toISOString() }), NOW).text).toContain('stopped arriving');
    expect(headline(null, NOW).text).toContain('No measurements');
  });

  it('formats values', () => {
    expect(num(sample(), 'main_agent', 'llm_tokens_per_second')).toBe(104.2);
    expect(num(sample(), 'main_agent', 'missing')).toBeNull();
    expect([hueFor(0.5), hueFor(0.8), hueFor(0.95)]).toEqual(['calm', 'warm', 'alert']);
    expect([gb(12_288), gb(4000)]).toEqual(['12', '3.9']);
    expect([rate(500), rate(2048), rate(3_145_728)]).toEqual(['500 B/s', '2 kB/s', '3.0 MB/s']);
  });
});
