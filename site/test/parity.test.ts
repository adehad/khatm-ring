import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, type Browser, type Page } from "playwright";
import { MODEL_DIR } from "../paths.ts";
import page from "./parity.html";

// Checks the WGSL port of the ring's distance field against ring_sdf.py, the
// build's own implementation, on a checkout of the build branch. Run it with
//   KHATM_BUILD=<build checkout> bun test
// Set KHATM_SWIFTSHADER=1 on machines without a GPU.

const BUILD = process.env["KHATM_BUILD"];
const SWIFTSHADER = process.env["KHATM_SWIFTSHADER"] === "1";

const SIZES_MM = [15.69, 19, 22.19];
const POINTS = 200_000;
// Float16 rasters and float32 arithmetic on both sides.
const NEAR_SURFACE_MM = 1;
const NEAR_TOLERANCE_MM = 0.002;
const FAR_TOLERANCE_MM = 0.01;
const SOLVE_TOLERANCE_MM = 0.02;
const VOLUME_TOLERANCE = 0.001;
const PUBLISHED_FACETS = 340_000;
const WEIGHT_TOLERANCE_G = 0.05;
const TIMEOUT_MS = 600_000;

interface Shape {
  readonly insideD: number;
  readonly wEnd: number;
  readonly tEnd: number;
  readonly plateExtra: number;
}

interface Stats {
  readonly volume_mm3: number;
  readonly band_end_width_mm: number;
  readonly band_end_thickness_mm: number;
  readonly plate_extra_mm: number;
}

interface Api {
  sample(shape: Shape): Promise<number[]>;
  volume(shape: Shape, h: number): Promise<number>;
  solve(insideD: number, targetG: number): Promise<Shape>;
  build(
    insideD: number,
    targetFacets: number,
  ): Promise<{
    seconds: number;
    grams: number;
    facets: number;
    openEdges: number;
    meshVolume: number;
    groups: number[];
  }>;
}

declare const khatm: Api;

function numberAt(value: unknown, path: readonly string[]): number {
  let at = value;
  for (const key of path) at = typeof at === "object" && at !== null ? Reflect.get(at, key) : undefined;
  if (typeof at !== "number")
    throw new TypeError(`no number at ${path.join(".")} in ${JSON.stringify(value)}`);
  return at;
}

// ring-sdf.json, for the target weight and the density.
const specJson: unknown = await Bun.file(join(MODEL_DIR, "ring-sdf.json")).json();
const TARGET_G = numberAt(specJson, ["target_g"]);
const DENSITY_G_MM3 = numberAt(specJson, ["sdf", "DENSITY_G_MM3"]);

let browser: Browser;
let tab: Page;
let points = new Float32Array(0);
let scratch = "";
const server = Bun.serve({
  port: 0,
  routes: {
    "/": page,
    "/ring-sdf.json": () => new Response(Bun.file(join(MODEL_DIR, "ring-sdf.json"))),
    "/face-fields.f16.xz": () => new Response(Bun.file(join(MODEL_DIR, "face-fields.f16.xz"))),
    "/points.f32": () => new Response(points),
  },
});

async function khatmSdf(args: readonly string[]): Promise<string> {
  if (BUILD === undefined) throw new Error("KHATM_BUILD is not set");
  const run = Bun.spawn(["uv", "run", "--project", BUILD, "khatm", "sdf", ...args], {
    stdout: "pipe",
    stderr: "pipe",
  });
  const [out, err, code] = await Promise.all([
    new Response(run.stdout).text(),
    new Response(run.stderr).text(),
    run.exited,
  ]);
  if (code !== 0) throw new Error(`khatm sdf ${args.join(" ")} failed:\n${err}`);
  return out;
}

function shapeArgs(shape: Shape): string[] {
  return [
    "--size",
    `${String(shape.insideD)} mm`,
    "--w-end",
    String(shape.wEnd),
    "--t-end",
    String(shape.tEnd),
    "--plate-extra",
    String(shape.plateExtra),
  ];
}

async function reference(shape: Shape): Promise<Float32Array> {
  const input = join(scratch, "points.f32");
  const output = join(scratch, "values.f32");
  await Bun.write(input, points);
  await khatmSdf([...shapeArgs(shape), "--sample", input, "--sample-out", output]);
  return new Float32Array(await Bun.file(output).arrayBuffer());
}

/** The stats line `khatm sdf` prints after meshing. */
async function meshStats(args: readonly string[]): Promise<Stats> {
  const out = await khatmSdf([...args, "--voxel", "0.1", "--out", join(scratch, "body.ply")]);
  const stats: unknown = JSON.parse(out.trim().split("\n").at(-1) ?? "null");
  return {
    volume_mm3: numberAt(stats, ["volume_mm3"]),
    band_end_width_mm: numberAt(stats, ["band_end_width_mm"]),
    band_end_thickness_mm: numberAt(stats, ["band_end_thickness_mm"]),
    plate_extra_mm: numberAt(stats, ["plate_extra_mm"]),
  };
}

/** Points spread over the ring's grid, the same box Ring.grid covers. */
function randomPoints(insideD: number): Float32Array<ArrayBuffer> {
  const r = insideD / 2 + 1.3 + 1.2;
  const lo = [-r, -8.9, -(insideD / 2 + 1.3 + 2)];
  const hi = [r, 8.9, insideD / 2 + 1.3 + 1.4 + 0.3];
  const xyz = new Float32Array(POINTS * 3);
  for (let i = 0; i < xyz.length; i++) {
    const axis = i % 3;
    const a = lo[axis] ?? 0;
    xyz[i] = a + Math.random() * ((hi[axis] ?? 0) - a);
  }
  return xyz;
}

async function openPage(): Promise<void> {
  scratch = await mkdtemp(join(tmpdir(), "khatm-parity-"));
  const args = ["--enable-unsafe-webgpu"];
  if (SWIFTSHADER) args.push("--use-webgpu-adapter=swiftshader", "--enable-unsafe-swiftshader");
  browser = await chromium.launch({ channel: "chromium", args });
  tab = await browser.newPage();
  tab.on("console", (message) => {
    console.log(`[page] ${message.text()}`);
  });
  tab.on("pageerror", (error) => {
    console.error(`[page] ${error.message}`);
  });
  await tab.goto(server.url.href);
  await tab.waitForSelector("body[data-ready]", { state: "attached", timeout: 60_000 });
}

async function closePage(): Promise<void> {
  await browser.close();
  await server.stop();
  await rm(scratch, { recursive: true, force: true });
}

async function checkField(insideD: number): Promise<void> {
  const shape = {
    insideD,
    wEnd: 2.6 + Math.random() * 2.4,
    tEnd: 0.8 + Math.random() * 0.5,
    plateExtra: Math.random() * 0.5,
  };
  points = randomPoints(insideD);
  const [expected, actual] = await Promise.all([
    reference(shape),
    tab.evaluate((s) => khatm.sample(s), shape),
  ]);
  let near = 0;
  let far = 0;
  expected.forEach((e, i) => {
    const diff = Math.abs(e - (actual[i] ?? Number.NaN));
    if (Math.abs(e) < NEAR_SURFACE_MM) near = Math.max(near, diff);
    else far = Math.max(far, diff);
  });
  console.log(
    `${String(insideD)} mm: largest difference ${near.toExponential(2)} near the surface, ${far.toExponential(2)} elsewhere`,
  );
  expect(near).toBeLessThan(NEAR_TOLERANCE_MM);
  expect(far).toBeLessThan(FAR_TOLERANCE_MM);
}

async function checkSolve(insideD: number): Promise<void> {
  const solved = await meshStats(["--size", `${String(insideD)} mm`, "--solve"]);
  const gpu = await tab.evaluate(([d, g]) => khatm.solve(d, g), [insideD, TARGET_G] as const);
  expect(Math.abs(gpu.wEnd - solved.band_end_width_mm)).toBeLessThan(SOLVE_TOLERANCE_MM);
  expect(Math.abs(gpu.tEnd - solved.band_end_thickness_mm)).toBeLessThan(SOLVE_TOLERANCE_MM);
  expect(Math.abs(gpu.plateExtra - solved.plate_extra_mm)).toBeLessThan(SOLVE_TOLERANCE_MM);

  const shape = {
    insideD,
    wEnd: solved.band_end_width_mm,
    tEnd: solved.band_end_thickness_mm,
    plateExtra: solved.plate_extra_mm,
  };
  const [expected, volume] = await Promise.all([
    meshStats(shapeArgs(shape)),
    tab.evaluate((s) => khatm.volume(s, 0.1), shape),
  ]);
  expect(Math.abs(volume - expected.volume_mm3) / expected.volume_mm3).toBeLessThan(VOLUME_TOLERANCE);
}

async function checkRebuild(): Promise<void> {
  const result = await tab.evaluate((f) => khatm.build(19, f), PUBLISHED_FACETS);
  console.log(`rebuild: ${JSON.stringify(result)}`);
  expect(result.openEdges).toBe(0);
  expect(Math.abs(result.grams - TARGET_G)).toBeLessThan(WEIGHT_TOLERANCE_G);
  expect(Math.abs(result.meshVolume * DENSITY_G_MM3 - result.grams)).toBeLessThan(WEIGHT_TOLERANCE_G);
  expect(result.groups[1]).toBeGreaterThan(0);
}

describe.skipIf(BUILD === undefined)("GPU field matches ring_sdf.py", () => {
  beforeAll(openPage, TIMEOUT_MS);
  afterAll(closePage);
  for (const insideD of SIZES_MM) {
    test(`field values at ${String(insideD)} mm`, () => checkField(insideD), TIMEOUT_MS);
    test(`band solve at ${String(insideD)} mm`, () => checkSolve(insideD), TIMEOUT_MS);
  }
  test("rebuilt mesh is closed and weighs what it was solved for", checkRebuild, TIMEOUT_MS);
});
