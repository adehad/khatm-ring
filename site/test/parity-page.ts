import type { RingShape } from "../src/gpu/grid.ts";
import { RingGpu } from "../src/gpu/ring-gpu.ts";
import { rebuildRing, signedVolume, solveBand, weld } from "../src/rebuild.ts";
import { loadRingSpec } from "../src/ring-spec.ts";
import { facetCount, parseRingStl } from "../src/stl.ts";

// Runs the GPU field in a real browser for parity.test.ts, which drives this
// page with Playwright and compares every answer with ring_sdf.py.

const spec = await loadRingSpec("/ring-sdf.json", "/face-fields.f16.xz");
const gpu = await RingGpu.create(spec);

/** Edges used other than once in each direction: zero for a closed, consistently wound mesh. */
function openEdges(indices: Uint32Array): number {
  const directed = new Map<string, number>();
  for (let i = 0; i < indices.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      const a = indices[i + k] ?? 0;
      const b = indices[i + ((k + 1) % 3)] ?? 0;
      const key = `${String(a)},${String(b)}`;
      directed.set(key, (directed.get(key) ?? 0) + 1);
    }
  }
  let bad = 0;
  for (const [key, count] of directed) {
    const [a, b] = key.split(",");
    if (count !== 1 || directed.get(`${b ?? ""},${a ?? ""}`) !== 1) bad += 1;
  }
  return bad;
}

const api = {
  async sample(shape: RingShape): Promise<number[]> {
    const points = new Float32Array(await (await fetch("/points.f32")).arrayBuffer());
    return [...(await gpu.sample(shape, points))];
  },
  volume(shape: RingShape, h: number): Promise<number> {
    return gpu.volume(shape, h);
  },
  solve(insideD: number, targetG: number): Promise<RingShape> {
    return solveBand(gpu, spec, insideD, targetG);
  },
  async build(insideD: number, targetFacets: number) {
    const started = performance.now();
    const built = await rebuildRing(gpu, spec, {
      insideD,
      build: "test",
      targetFacets,
      onStage: () => {
        // The test times the whole rebuild instead.
      },
    });
    const seconds = (performance.now() - started) / 1000;
    const { geometry } = parseRingStl(built.stl);
    const facets = facetCount(built.stl);
    const soup = new Float32Array(facets * 9);
    const view = new DataView(built.stl);
    for (let f = 0; f < facets; f++) {
      for (let i = 0; i < 9; i++) soup[f * 9 + i] = view.getFloat32(84 + f * 50 + 12 + i * 4, true);
    }
    const { positions, indices } = weld(soup);
    return {
      seconds,
      shape: built.shape,
      grams: built.info.grams,
      facets,
      openEdges: openEdges(indices),
      meshVolume: signedVolume(positions, indices),
      groups: geometry.groups.map((g) => g.count / 3),
    };
  },
};

Object.assign(globalThis, { khatm: api });
document.body.dataset["ready"] = "true";
