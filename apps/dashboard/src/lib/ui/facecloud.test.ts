import { describe, expect, it } from 'vitest';
import shipped from './face-cloud.bin?inline';
import { parseFaceCloud, particleAt, RECORD_BYTES } from './facecloud';

/** The shipped file, which the bundler hands to the test as a data URL. */
function fileBuffer(): ArrayBuffer {
  const binary = atob(shipped.slice(shipped.indexOf(',') + 1));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function tiny(count: number, declared = count): ArrayBuffer {
  const buffer = new ArrayBuffer(16 + count * RECORD_BYTES);
  const view = new DataView(buffer);
  view.setUint32(0, 0x31434654, true);
  view.setUint32(4, declared, true);
  view.setFloat32(8, 0.0135, true);
  return buffer;
}

describe('face cloud', () => {
  it('reads the header and one record per particle', () => {
    const buffer = tiny(2);
    const view = new DataView(buffer);
    view.setInt16(16 + 12, 8192, true); // second particle: x = 1 face unit
    view.setInt16(16 + 14, -16384, true); // y = -2
    view.setUint8(16 + 18, 255); // b
    view.setUint8(16 + 20, 128); // jaw
    view.setInt8(16 + 23, -127); // ny
    const cloud = parseFaceCloud(buffer);
    expect(cloud.count).toBe(2);
    expect(cloud.spacing).toBeCloseTo(0.0135, 5);
    const p = particleAt(cloud, 1);
    expect(p.x).toBeCloseTo(1, 3);
    expect(p.y).toBeCloseTo(-2, 3);
    expect(p.b).toBe(1);
    expect(p.jaw).toBeCloseTo(0.5, 2);
    expect(p.ny).toBe(-1);
    expect(particleAt(cloud, 0)).toMatchObject({ x: 0, y: 0, z: 0, b: 0, edge: 0 });
  });

  it('refuses files that are not a face cloud', () => {
    expect(() => parseFaceCloud(new ArrayBuffer(4))).toThrow(/too short/);
    expect(() => parseFaceCloud(new ArrayBuffer(64))).toThrow(/not a face cloud/);
    expect(() => parseFaceCloud(tiny(2, 3))).toThrow(/size/);
  });

  it('ships a face: dense, within range, with a jaw, lips and loose particles around it', () => {
    const cloud = parseFaceCloud(fileBuffer());
    expect(cloud.count).toBeGreaterThan(12_000);
    expect(cloud.count).toBeLessThan(40_000);
    const all = Array.from({ length: cloud.count }, (_, i) => particleAt(cloud, i));
    const solid = all.filter((p) => p.edge < 0.3);
    const loose = all.filter((p) => p.edge > 0.8);
    expect(solid.length).toBeGreaterThan(cloud.count * 0.6);
    expect(loose.length).toBeGreaterThan(cloud.count * 0.1);
    expect(solid.every((p) => Math.abs(p.x) < 1.2 && p.y > -1.4 && p.y < 1.4 && Math.abs(p.z) < 1)).toBe(true);
    expect(all.every((p) => p.nx * p.nx + p.ny * p.ny <= 1.02)).toBe(true);
    // The nose stands in front of the cheeks.
    const depth = (cx: number, cy: number) => {
      const near = solid.filter((p) => Math.hypot(p.x - cx, p.y - cy) < 0.08);
      return near.reduce((sum, p) => sum + p.z, 0) / near.length;
    };
    expect(depth(0, 0.05)).toBeGreaterThan(depth(0.45, 0.05) + 0.15);
    // The jaw moves what is below the lips, and nothing above the nose.
    const dropping = all.filter((p) => p.jaw > 0.6);
    expect(dropping.length).toBeGreaterThan(500);
    expect(dropping.every((p) => p.y > 0.5)).toBe(true);
    expect(all.filter((p) => p.y < 0.2).every((p) => p.jaw < 0.05)).toBe(true);
    expect(all.filter((p) => p.mouth > 0.8).every((p) => Math.abs(p.x) < 0.35 && p.y > 0.4 && p.y < 0.9)).toBe(true);
    expect(loose.every((p) => p.jaw === 0)).toBe(true);
  });

  it('is shuffled, so a first part of the file is an even sample of the whole face', () => {
    const cloud = parseFaceCloud(fileBuffer());
    const share = (from: number, to: number) => {
      let upper = 0;
      for (let i = from; i < to; i++) if (particleAt(cloud, i).y < 0) upper++;
      return upper / (to - from);
    };
    expect(Math.abs(share(0, 3000) - share(0, cloud.count))).toBeLessThan(0.04);
  });
});
