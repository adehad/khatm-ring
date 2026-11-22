import { MeshoptSimplifier } from "meshoptimizer";
import { fieldHeight, type RingShape } from "./gpu/grid.ts";
import type { RingGpu } from "./gpu/ring-gpu.ts";
import { sdfNumber, sdfRange, type RingSpec } from "./ring-spec.ts";
import { sizeNames } from "./sizes.ts";
import { VertexWelder, writeRingStl, type RingInfo } from "./stl.ts";

// The build's steps for one ring, on the GPU: ring_sdf.solve_band, then
// marching cubes at `khatm sdf`'s default voxel, then a decimation to about
// the published STL's facet count, as the Blender build does.

const SOLVE_VOXEL_MM = 0.1;
const MESH_VOXEL_MM = 0.05;
const SECANT_ROUNDS = 6;
const SECANT_TOLERANCE_MM3 = 1;
const WIDTH_STEP_MM = 0.5;
const THICKNESS_STEP_MM = 0.1;
const PLATE_STEP_MM = 0.1;
// meshoptimizer stops collapsing edges before the surface moves further.
const SIMPLIFY_ERROR_MM = 0.005;
const WEIGHT_TOLERANCE_G = 0.05;

export type Stage = "solving" | "meshing" | "weighing" | "simplifying";

export interface BuiltRing {
  readonly stl: ArrayBuffer;
  readonly info: RingInfo;
  readonly shape: RingShape;
  /** False when the band's ends hit their limits before the target weight. */
  readonly reachedTarget: boolean;
}

type Volume = (x: number) => Promise<number>;

/** ring_sdf.secant: x within bounds where volume(x) meets target, to within 1 mm³. */
async function secant(
  volume: Volume,
  x0: number,
  step: number,
  [lo, hi]: readonly [number, number],
  target: number,
): Promise<readonly [number, number]> {
  const clip = (x: number): number => Math.min(Math.max(x, lo), hi);
  let a = [x0, await volume(x0)] as const;
  const bx = clip(x0 + (a[1] < target ? step : -step));
  let b = [bx, await volume(bx)] as const;
  for (let round = 0; round < SECANT_ROUNDS; round++) {
    if (Math.abs(b[1] - target) < SECANT_TOLERANCE_MM3 || b[1] === a[1]) break;
    const x = clip(b[0] - ((b[1] - target) * (b[0] - a[0])) / (b[1] - a[1]));
    a = b;
    // oxlint-disable-next-line no-await-in-loop -- each step needs the last
    b = [x, await volume(x)] as const;
  }
  return b;
}

/**
 * ring_sdf.solve_band: the end width first; then, at its widest, the plate's
 * extra thickness, or at its narrowest, the end thickness.
 */
export async function solveBand(
  gpu: RingGpu,
  spec: RingSpec,
  insideD: number,
  targetG: number,
): Promise<RingShape> {
  const target = targetG / sdfNumber(spec, "DENSITY_G_MM3");
  const tEnd = sdfNumber(spec, "BAND_T_END");
  const plateExtra = sdfNumber(spec, "PLATE_EXTRA");
  const [narrowest, widest] = sdfRange(spec, "BAND_W_END_RANGE");
  const [wEnd, v] = await secant(
    (w) => gpu.volume({ insideD, wEnd: w, tEnd, plateExtra }, SOLVE_VOXEL_MM),
    sdfNumber(spec, "BAND_W_END"),
    WIDTH_STEP_MM,
    [narrowest, widest],
    target,
  );
  const shape = { insideD, wEnd, tEnd, plateExtra };
  if (Math.abs(v - target) <= SECANT_TOLERANCE_MM3) return shape;
  if (wEnd === widest) {
    const [plate] = await secant(
      (extra) => gpu.volume({ ...shape, plateExtra: extra }, SOLVE_VOXEL_MM),
      plateExtra,
      PLATE_STEP_MM,
      sdfRange(spec, "PLATE_EXTRA_RANGE"),
      target,
    );
    return { ...shape, plateExtra: plate };
  }
  if (wEnd === narrowest) {
    const [t] = await secant(
      (thickness) => gpu.volume({ ...shape, tEnd: thickness }, SOLVE_VOXEL_MM),
      tEnd,
      THICKNESS_STEP_MM,
      sdfRange(spec, "BAND_T_END_RANGE"),
      target,
    );
    return { ...shape, tEnd: t };
  }
  return shape;
}

/** Merges the soup's shared corners and drops triangles that collapse to a line. */
export function weld(soup: Float32Array): { positions: Float32Array; indices: Uint32Array } {
  const welder = new VertexWelder(soup.length / 3);
  const bits = new Uint32Array(soup.buffer, soup.byteOffset, soup.length);
  const indices = new Uint32Array(soup.length / 3);
  let n = 0;
  for (let o = 0; o < soup.length; o += 9) {
    const a = welder.add(soup, bits, o);
    const b = welder.add(soup, bits, o + 3);
    const c = welder.add(soup, bits, o + 6);
    if (a !== b && b !== c && a !== c) {
      indices.set([a, b, c], n);
      n += 3;
    }
  }
  return { positions: welder.vertices(), indices: indices.slice(0, n) };
}

export function signedVolume(positions: Float32Array, indices: Uint32Array): number {
  let six = 0;
  for (let i = 0; i < indices.length; i += 3) {
    const a = (indices[i] ?? 0) * 3;
    const b = (indices[i + 1] ?? 0) * 3;
    const c = (indices[i + 2] ?? 0) * 3;
    const [ax, ay, az] = [positions[a] ?? 0, positions[a + 1] ?? 0, positions[a + 2] ?? 0];
    const [bx, by, bz] = [positions[b] ?? 0, positions[b + 1] ?? 0, positions[b + 2] ?? 0];
    const [cx, cy, cz] = [positions[c] ?? 0, positions[c + 1] ?? 0, positions[c + 2] ?? 0];
    six += ax * (by * cz - bz * cy) + ay * (bz * cx - bx * cz) + az * (bx * cy - by * cx);
  }
  return six / 6;
}

/**
 * Drops pairs of triangles on the same three vertices with opposite windings.
 * Decimation leaves a few where it folds a thin pocket flat; each pair
 * encloses nothing, and without it the mesh is closed again.
 */
export function dropFolds(indices: Uint32Array): Uint32Array {
  const seen = new Map<string, number>();
  const dropped = new Set<number>();
  for (let i = 0; i < indices.length; i += 3) {
    const corners = [indices[i] ?? 0, indices[i + 1] ?? 0, indices[i + 2] ?? 0];
    const key = corners.toSorted((x, y) => x - y).join(",");
    const twin = seen.get(key);
    if (twin === undefined) {
      seen.set(key, i);
    } else {
      dropped.add(twin).add(i);
      seen.delete(key);
    }
  }
  if (dropped.size === 0) return indices;
  return indices.filter((_, i) => !dropped.has(i - (i % 3)));
}

/** Winds every triangle the other way. */
function flip(indices: Uint32Array): void {
  for (let i = 0; i < indices.length; i += 3) {
    const b = indices[i + 1] ?? 0;
    indices[i + 1] = indices[i + 2] ?? 0;
    indices[i + 2] = b;
  }
}

export interface RebuildOptions {
  readonly insideD: number;
  /** The published STL's build commit, which this port of its field belongs to. */
  readonly build: string;
  readonly targetFacets: number;
  readonly onStage: (stage: Stage, fraction: number) => void;
}

export async function rebuildRing(gpu: RingGpu, spec: RingSpec, options: RebuildOptions): Promise<BuiltRing> {
  const { insideD, onStage } = options;
  onStage("solving", 0);
  const shape = await solveBand(gpu, spec, insideD, spec.targetG);
  const soup = await gpu.mesh(shape, MESH_VOXEL_MM, (fraction) => {
    onStage("meshing", fraction);
  });
  onStage("weighing", 0);
  const grams = (await gpu.volume(shape, MESH_VOXEL_MM)) * sdfNumber(spec, "DENSITY_G_MM3");

  onStage("simplifying", 0);
  const { positions, indices } = weld(soup);
  await MeshoptSimplifier.ready;
  const [simplified] = MeshoptSimplifier.simplify(
    indices,
    positions,
    3,
    options.targetFacets * 3,
    SIMPLIFY_ERROR_MM,
    ["ErrorAbsolute"],
  );
  const closed = dropFolds(simplified);
  if (signedVolume(positions, closed) < 0) flip(closed);

  const names = sizeNames(spec.ringSize, insideD);
  const info: RingInfo = {
    build: options.build,
    fieldZ: fieldHeight(spec, insideD),
    grams,
    insideDiameter: insideD,
    us: names.us,
    uk: names.uk,
  };
  return {
    stl: writeRingStl(positions, closed, info),
    info,
    shape,
    reachedTarget: Math.abs(grams - spec.targetG) <= WEIGHT_TOLERANCE_G,
  };
}
