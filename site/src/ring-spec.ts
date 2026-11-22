import { XzReadableStream } from "xz-decompress";

// ring-sdf.json and face-fields.f16.xz, which `khatm publish` writes beside
// the STL: the distance field's constants and its two face rasters.

export interface RingSpec {
  /** ring_sdf.py's module constants, by name. */
  readonly sdf: ReadonlyMap<string, number | readonly number[]>;
  readonly ringSize: SizeScales;
  readonly targetG: number;
  readonly rasterRows: number;
  readonly rasterCols: number;
  /** Two float16 layers, field outline then letters, row-major. */
  readonly rasters: Uint16Array;
}

export interface SizeScales {
  readonly usZeroMm: number;
  readonly usStepMm: number;
  readonly ukACircMm: number;
  readonly ukStepMm: number;
  readonly ukLetters: string;
}

const RASTER_LAYERS = ["field", "letters"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, what: string): Record<string, unknown> {
  if (!isRecord(value)) throw new TypeError(`ring-sdf.json: ${what} is not an object`);
  return value;
}

function num(value: unknown, what: string): number {
  if (typeof value !== "number") throw new TypeError(`ring-sdf.json: ${what} is not a number`);
  return value;
}

function sdfConstants(raw: Record<string, unknown>): Map<string, number | readonly number[]> {
  const constants = new Map<string, number | readonly number[]>();
  for (const [name, value] of Object.entries(raw)) {
    if (typeof value === "number") constants.set(name, value);
    else if (Array.isArray(value))
      constants.set(
        name,
        value.map((v, i) => num(v, `${name}[${i}]`)),
      );
  }
  return constants;
}

export function sdfNumber(spec: RingSpec, name: string): number {
  const value = spec.sdf.get(name);
  if (typeof value !== "number") throw new TypeError(`ring-sdf.json has no number ${name}`);
  return value;
}

export function sdfRange(spec: RingSpec, name: string): readonly [number, number] {
  const value = spec.sdf.get(name);
  if (!Array.isArray(value) || value.length !== 2) throw new TypeError(`ring-sdf.json has no range ${name}`);
  const [lo, hi] = value as readonly number[];
  if (lo === undefined || hi === undefined) throw new TypeError(`ring-sdf.json has no range ${name}`);
  return [lo, hi];
}

function parseSpec(json: unknown, rasters: Uint16Array): RingSpec {
  const root = record(json, "the file");
  const sizes = record(root["ring_size"], "ring_size");
  const face = record(root["face_rasters"], "face_rasters");
  const layers = face["layers"];
  if (JSON.stringify(layers) !== JSON.stringify(RASTER_LAYERS)) {
    throw new Error(
      `ring-sdf.json: face rasters are ${JSON.stringify(layers)}, not ${JSON.stringify(RASTER_LAYERS)}`,
    );
  }
  const rows = num(face["rows"], "face_rasters.rows");
  const cols = num(face["cols"], "face_rasters.cols");
  if (rasters.length !== RASTER_LAYERS.length * rows * cols) {
    throw new Error(
      `face-fields.f16.xz has ${rasters.length} values, not ${RASTER_LAYERS.length}×${rows}×${cols}`,
    );
  }
  const letters = sizes["UK_LETTERS"];
  if (typeof letters !== "string") throw new TypeError("ring-sdf.json: ring_size.UK_LETTERS is not a string");
  return {
    sdf: sdfConstants(record(root["sdf"], "sdf")),
    ringSize: {
      usZeroMm: num(sizes["US_ZERO_MM"], "US_ZERO_MM"),
      usStepMm: num(sizes["US_STEP_MM"], "US_STEP_MM"),
      ukACircMm: num(sizes["UK_A_CIRC_MM"], "UK_A_CIRC_MM"),
      ukStepMm: num(sizes["UK_STEP_MM"], "UK_STEP_MM"),
      ukLetters: letters,
    },
    targetG: num(root["target_g"], "target_g"),
    rasterRows: rows,
    rasterCols: cols,
    rasters,
  };
}

async function fetchOk(url: string): Promise<Response> {
  const response = await fetch(url);
  if (!response.ok || response.body === null) throw new Error(`${url}: HTTP ${response.status}`);
  return response;
}

async function fetchJson(url: string): Promise<unknown> {
  const json: unknown = await (await fetchOk(url)).json();
  return json;
}

async function fetchXz(url: string): Promise<ArrayBuffer> {
  const packed = await fetchOk(url);
  if (packed.body === null) throw new Error(`${url}: empty response`);
  return new Response(new XzReadableStream(packed.body)).arrayBuffer();
}

export async function loadRingSpec(specUrl: string, rastersUrl: string): Promise<RingSpec> {
  const [json, bytes] = await Promise.all([fetchJson(specUrl), fetchXz(rastersUrl)]);
  return parseSpec(json, new Uint16Array(bytes));
}
