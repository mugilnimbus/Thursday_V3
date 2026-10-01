/* Turn timed samples into chart paths. Pure, so it is unit tested.

   - The x axis is time: a sample sits where it happened inside the chosen period, so a stretch with
     no samples (Thursday was not running) shows as a break in the line, not as a straight join.
   - Samples are averaged into equal time slots, so the shape does not depend on how many there are.
   - The y axis fits the data: from zero for load-like values (CPU, network, latency), or zoomed to the
     range actually seen for level-like values (memory), where the changes would otherwise look flat. */

export interface Point {
  t: number; // epoch milliseconds
  v: number;
}

export interface Chart {
  /** One SVG path per unbroken stretch of line, in a 100 by 40 box. */
  lines: string[];
  /** The same stretches closed down to the bottom, for the fill. */
  areas: string[];
  /** Isolated samples with no neighbour to connect to. */
  dots: { x: number; y: number }[];
  min: number | null;
  max: number | null;
}

export const SLOTS = 90;
const TOP = 4;
const BOTTOM = 40;

/** Average value per time slot; null where the slot has no sample. */
export function slots(points: Point[], from: number, to: number, count = SLOTS): (number | null)[] {
  const sum = new Array<number>(count).fill(0);
  const n = new Array<number>(count).fill(0);
  const width = (to - from) / count;
  for (const p of points) {
    if (p.t < from || p.t > to || !Number.isFinite(p.v)) continue;
    const i = Math.min(count - 1, Math.floor((p.t - from) / width));
    sum[i] += p.v;
    n[i] += 1;
  }
  return sum.map((s, i) => (n[i] ? s / n[i] : null));
}

export interface ChartOptions {
  /** Start the y axis at zero (loads). Otherwise it is fitted to the data (levels). */
  zero?: boolean;
  /** A fixed top for the y axis (for example 100 for percent). */
  ceiling?: number;
  /** Join samples across empty slots (for occasional events such as model calls). */
  sparse?: boolean;
}

export function buildChart(values: (number | null)[], options: ChartOptions = {}): Chart {
  const present = values.filter((v): v is number => v !== null);
  if (!present.length) return { lines: [], areas: [], dots: [], min: null, max: null };
  const min = Math.min(...present);
  const max = Math.max(...present);
  let low: number;
  let high: number;
  if (options.zero) {
    low = 0;
    high = options.ceiling ?? Math.max(max * 1.1, 1e-9);
  } else {
    const pad = Math.max((max - min) * 0.15, Math.abs(max) * 0.02, 1e-9);
    low = Math.max(0, min - pad);
    high = options.ceiling !== undefined ? Math.min(options.ceiling, max + pad) : max + pad;
    if (high <= low) high = low + 1;
  }
  const x = (i: number) => (values.length === 1 ? 50 : (i / (values.length - 1)) * 100);
  const y = (v: number) => BOTTOM - ((Math.min(Math.max(v, low), high) - low) / (high - low)) * (BOTTOM - TOP);

  const runs: { x: number; y: number }[][] = [];
  let run: { x: number; y: number }[] = [];
  values.forEach((v, i) => {
    if (v === null) {
      if (!options.sparse && run.length) {
        runs.push(run);
        run = [];
      }
      return;
    }
    run.push({ x: x(i), y: y(v) });
  });
  if (run.length) runs.push(run);

  const chart: Chart = { lines: [], areas: [], dots: [], min, max };
  for (const points of runs) {
    if (points.length === 1) {
      chart.dots.push(points[0]);
      continue;
    }
    let d = `M${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
    for (let i = 1; i < points.length; i++) {
      const mid = ((points[i - 1].x + points[i].x) / 2).toFixed(2);
      d += ` C${mid} ${points[i - 1].y.toFixed(2)} ${mid} ${points[i].y.toFixed(2)} ${points[i].x.toFixed(2)} ${points[i].y.toFixed(2)}`;
    }
    chart.lines.push(d);
    chart.areas.push(`${d} L${points.at(-1)!.x.toFixed(2)} ${BOTTOM} L${points[0].x.toFixed(2)} ${BOTTOM} Z`);
    if (options.sparse) chart.dots.push(...points);
  }
  return chart;
}

const SPAN_TEXT: Record<string, string> = { '15m': 'the last 15 minutes', '1h': 'the last hour', '24h': 'the last 24 hours', '7d': 'the last 7 days' };

export function spanText(range: string): string {
  return SPAN_TEXT[range] ?? range;
}

/** "3 min ago" style age for a model call. */
export function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86_400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86_400)} d ago`;
}
