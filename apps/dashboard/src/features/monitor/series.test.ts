import { describe, expect, it } from 'vitest';
import { ago, buildChart, slots } from './series';

describe('time slots', () => {
  it('places samples by time and leaves empty slots where there is no data', () => {
    const points = [{ t: 0, v: 10 }, { t: 50, v: 20 }, { t: 950, v: 40 }, { t: 999, v: 60 }];
    expect(slots(points, 0, 1000, 10)).toEqual([15, null, null, null, null, null, null, null, null, 50]);
  });

  it('ignores samples outside the period', () => {
    expect(slots([{ t: -5, v: 1 }, { t: 2000, v: 1 }], 0, 1000, 4)).toEqual([null, null, null, null]);
  });
});

describe('chart', () => {
  it('breaks the line across a gap instead of joining it', () => {
    const chart = buildChart([1, 2, 3, null, null, 4, 5]);
    expect(chart.lines).toHaveLength(2);
    expect(chart.areas).toHaveLength(2);
  });

  it('joins occasional events and marks each one', () => {
    const chart = buildChart([80, null, null, 100, null, 90], { sparse: true });
    expect(chart.lines).toHaveLength(1);
    expect(chart.dots).toHaveLength(3);
  });

  it('fits level-like values to their own range so changes are visible', () => {
    const flat = buildChart([10_000, 10_100, 10_050], { zero: true, ceiling: 12_288 });
    const fitted = buildChart([10_000, 10_100, 10_050]);
    const ys = (d: string) => [...d.matchAll(/ (\d+\.\d+)(?= C|$)/g)].map((m) => Number(m[1]));
    const spread = (d: string) => Math.max(...ys(d)) - Math.min(...ys(d));
    expect(spread(fitted.lines[0])).toBeGreaterThan(spread(flat.lines[0]) * 10);
    expect([fitted.min, fitted.max]).toEqual([10_000, 10_100]);
  });

  it('shows a single sample as a dot and nothing for no data', () => {
    expect(buildChart([null, 5, null]).dots).toHaveLength(1);
    expect(buildChart([null, null])).toEqual({ lines: [], areas: [], dots: [], min: null, max: null });
  });
});

it('describes how long ago a call was', () => {
  expect([ago(5000), ago(180_000), ago(7_200_000)]).toEqual(['5 s ago', '3 min ago', '2 h ago']);
});
