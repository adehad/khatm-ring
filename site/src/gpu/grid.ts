import { sdfNumber, type RingSpec } from "../ring-spec.ts";

// The sizes and grid ring_sdf.py derives from the finger, and the WGSL for
// its named constants.

/** What sets one ring apart from another: the finger, and the band's ends. */
export interface RingShape {
  readonly insideD: number;
  readonly wEnd: number;
  readonly tEnd: number;
}

export interface Grid {
  readonly origin: readonly [number, number, number];
  readonly dims: readonly [number, number, number];
  readonly h: number;
}

// ring_sdf.set_size: every height on the ring is measured from the finger.
export function sizeValues(spec: RingSpec, insideD: number) {
  const rFinger = insideD / 2;
  const bandT = sdfNumber(spec, "BAND_T_ROOT");
  const zTop = rFinger + bandT + 1.4;
  return { rFinger, rSaddle: rFinger + bandT / 2, zTop, zField: zTop - sdfNumber(spec, "RELIEF") };
}

/** Ring.grid: np.arange(lo, hi + h, h) on each axis. */
export function ringGrid(spec: RingSpec, insideD: number, h: number): Grid {
  const { rFinger, zTop } = sizeValues(spec, insideD);
  const bandT = sdfNumber(spec, "BAND_T_ROOT");
  const half = sdfNumber(spec, "FACE_D") / 2;
  const lo = [-rFinger - bandT - 1.2, -half - 0.4, -rFinger - bandT - 2.0] as const;
  const hi = [rFinger + bandT + 1.2, half + 0.4, zTop + 0.3] as const;
  const count = (a: number, b: number): number => Math.ceil((b + h - a) / h);
  return { origin: lo, dims: [count(lo[0], hi[0]), count(lo[1], hi[1]), count(lo[2], hi[2])], h };
}

export function fieldHeight(spec: RingSpec, insideD: number): number {
  return sizeValues(spec, insideD).zField;
}

export function wgslConstants(spec: RingSpec): string {
  const lines: string[] = [];
  for (const [name, value] of spec.sdf) {
    if (typeof value === "number") lines.push(`const ${name}: f32 = ${String(value)};`);
  }
  return lines.join("\n");
}
