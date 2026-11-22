import * as THREE from "three";

// Binary STL: an 80-byte header, a uint32 facet count, then 50 bytes per facet
// (normal, three vertices, attribute). The build writes `key=value` pairs into
// the header and zeroes the normals, which are recomputed here.
const HEADER_BYTES = 80;
const FACET_BYTES = 50;
const FIELD_TOLERANCE_MM = 0.06;
const UPWARD = 0.8;

export interface RingInfo {
  /** The build branch commit the STL came from; a trailing "+" marks uncommitted changes. */
  readonly build: string;
  readonly fieldZ: number;
  readonly grams: number;
  readonly insideDiameter: number;
  readonly us: string;
  readonly uk: string;
}

export interface RingMesh {
  readonly geometry: THREE.BufferGeometry;
  readonly info: RingInfo;
}

// Material slots on the geometry's groups.
export const Group = { Silver: 0, Field: 1 } as const;

const HEADER_KEYS = ["build", "field_z", "grams", "inside_d", "us", "uk"] as const;

function headerText(info: RingInfo): string {
  const values: Record<(typeof HEADER_KEYS)[number], string> = {
    build: info.build,
    field_z: info.fieldZ.toFixed(4),
    grams: info.grams.toFixed(2),
    inside_d: info.insideDiameter.toFixed(2),
    us: info.us,
    uk: info.uk,
  };
  return `khatm ${HEADER_KEYS.map((key) => `${key}=${values[key]}`).join(" ")}`;
}

/** A binary STL in the build's format: header pairs, zeroed normals. */
export function writeRingStl(positions: Float32Array, indices: Uint32Array, info: RingInfo): ArrayBuffer {
  const text = headerText(info);
  if (text.length > HEADER_BYTES)
    throw new Error(`STL header is ${text.length} bytes, over ${HEADER_BYTES}: ${text}`);
  const facets = indices.length / 3;
  const buffer = new ArrayBuffer(HEADER_BYTES + 4 + facets * FACET_BYTES);
  const bytes = new Uint8Array(buffer);
  bytes.fill(" ".codePointAt(0) ?? 0, 0, HEADER_BYTES);
  new TextEncoder().encodeInto(text, bytes);
  const view = new DataView(buffer);
  view.setUint32(HEADER_BYTES, facets, true);
  for (let f = 0; f < facets; f++) {
    const base = HEADER_BYTES + 4 + f * FACET_BYTES + 12;
    for (let corner = 0; corner < 3; corner++) {
      const v = (indices[f * 3 + corner] ?? 0) * 3;
      for (let axis = 0; axis < 3; axis++) {
        view.setFloat32(base + (corner * 3 + axis) * 4, positions[v + axis] ?? 0, true);
      }
    }
  }
  return buffer;
}

function parseHeader(bytes: Uint8Array): RingInfo {
  const text = new TextDecoder("ascii").decode(bytes.subarray(0, HEADER_BYTES));
  const pairs = new Map(
    text
      .trim()
      .split(/\s+/u)
      .flatMap((token) => {
        const eq = token.indexOf("=");
        return eq > 0 ? [[token.slice(0, eq), token.slice(eq + 1)] as const] : [];
      }),
  );
  const need = (key: string): string => {
    const value = pairs.get(key);
    if (value === undefined) throw new Error(`STL header has no ${key}: "${text.trim()}"`);
    return value;
  };
  return {
    build: need("build"),
    fieldZ: Number(need("field_z")),
    grams: Number(need("grams")),
    insideDiameter: Number(need("inside_d")),
    us: need("us"),
    uk: need("uk"),
  };
}

// Merges the corners STL repeats for every facet, so normals can be smoothed
// across facets. Keys are the exact float bits: the mesher writes shared
// corners identically.
export class VertexWelder {
  private readonly slots: Int32Array;
  private readonly mask: number;
  private readonly positions: Float32Array;
  private readonly bits: Uint32Array;
  private count = 0;

  constructor(maxVertices: number) {
    let size = 1;
    while (size < maxVertices * 2) size <<= 1;
    this.slots = new Int32Array(size).fill(-1);
    this.mask = size - 1;
    this.positions = new Float32Array(maxVertices * 3);
    this.bits = new Uint32Array(this.positions.buffer);
  }

  /** The index of the vertex at `xyz[offset..offset+2]`, whose float bits are `bits` at the same place. */
  add(xyz: Float32Array, bits: Uint32Array, offset: number): number {
    const xb = bits[offset] ?? 0;
    const yb = bits[offset + 1] ?? 0;
    const zb = bits[offset + 2] ?? 0;
    let h = (Math.imul(xb, 0x9e3779b1) ^ Math.imul(yb, 0x85ebca77) ^ Math.imul(zb, 0xc2b2ae3d)) & this.mask;
    for (let slot = this.slots[h] ?? -1; slot !== -1; slot = this.slots[h] ?? -1) {
      const o = slot * 3;
      if (this.bits[o] === xb && this.bits[o + 1] === yb && this.bits[o + 2] === zb) return slot;
      h = (h + 1) & this.mask;
    }
    const index = this.count;
    this.count += 1;
    this.slots[h] = index;
    this.positions.set(xyz.subarray(offset, offset + 3), index * 3);
    return index;
  }

  vertices(): Float32Array {
    return this.positions.slice(0, this.count * 3);
  }
}

interface SplitFacets {
  readonly vertices: Float32Array;
  readonly silver: readonly number[];
  readonly field: readonly number[];
}

// Welds the facets' corners and sorts the facets into the oxidised field and
// the rest. The recessed field is the only upward face at field height; the
// letter tops and the rim stand higher.
function splitFacets(view: DataView, facets: number, fieldZ: number): SplitFacets {
  const welder = new VertexWelder(facets * 3);
  const silver: number[] = [];
  const field: number[] = [];
  const corners = new Float32Array(9);
  const bits = new Uint32Array(corners.buffer);
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  for (let f = 0; f < facets; f++) {
    const base = HEADER_BYTES + 4 + f * FACET_BYTES + 12;
    for (let i = 0; i < 9; i++) corners[i] = view.getFloat32(base + i * 4, true);
    a.fromArray(corners, 0);
    b.fromArray(corners, 3);
    c.fromArray(corners, 6);
    const up = b.clone().sub(a).cross(c.clone().sub(a)).normalize().z;
    const centreZ = (a.z + b.z + c.z) / 3;
    const isField = up > UPWARD && Math.abs(centreZ - fieldZ) < FIELD_TOLERANCE_MM;
    (isField ? field : silver).push(
      welder.add(corners, bits, 0),
      welder.add(corners, bits, 3),
      welder.add(corners, bits, 6),
    );
  }
  return { vertices: welder.vertices(), silver, field };
}

export function facetCount(stl: ArrayBuffer): number {
  return new DataView(stl).getUint32(HEADER_BYTES, true);
}

export function parseRingStl(buffer: ArrayBuffer): RingMesh {
  const view = new DataView(buffer);
  const info = parseHeader(new Uint8Array(buffer));
  const facets = view.getUint32(HEADER_BYTES, true);
  if (buffer.byteLength < HEADER_BYTES + 4 + facets * FACET_BYTES) {
    throw new Error(`STL is truncated: ${facets} facets need more than ${buffer.byteLength} bytes`);
  }
  const { vertices, silver, field } = splitFacets(view, facets, info.fieldZ);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(vertices, 3));
  geometry.setIndex([...silver, ...field]);
  geometry.addGroup(0, silver.length, Group.Silver);
  geometry.addGroup(silver.length, field.length, Group.Field);
  // STL is Z-up; three.js is Y-up.
  geometry.rotateX(-Math.PI / 2);
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  return { geometry, info };
}
