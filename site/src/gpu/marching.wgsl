// Marching cubes over one slab of the field that ring.wgsl's `field` wrote.
// Corners and edges follow Paul Bourke's numbering, which the triangle table
// from three.js uses. Each edge is interpolated from its lower corner to its
// upper one, from integer grid coordinates, so the two cells that share an
// edge write bit-identical vertices and the mesh welds exactly.

@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> values: array<f32>;
@group(0) @binding(2) var<storage, read> tri_table: array<i32>;
@group(0) @binding(3) var<storage, read_write> written: atomic<u32>;
// Nine floats per triangle. Triangles past P.capacity are counted, not written.
@group(0) @binding(4) var<storage, read_write> triangles: array<f32>;

var<private> CORNERS: array<vec3u, 8> = array<vec3u, 8>(
  vec3u(0u, 0u, 0u), vec3u(1u, 0u, 0u), vec3u(1u, 1u, 0u), vec3u(0u, 1u, 0u),
  vec3u(0u, 0u, 1u), vec3u(1u, 0u, 1u), vec3u(1u, 1u, 1u), vec3u(0u, 1u, 1u),
);
var<private> EDGES: array<vec2u, 12> = array<vec2u, 12>(
  vec2u(0u, 1u), vec2u(1u, 2u), vec2u(3u, 2u), vec2u(0u, 3u),
  vec2u(4u, 5u), vec2u(5u, 6u), vec2u(7u, 6u), vec2u(4u, 7u),
  vec2u(0u, 4u), vec2u(1u, 5u), vec2u(2u, 6u), vec2u(3u, 7u),
);

fn value_at(i: vec3u) -> f32 {
  return values[i.x + P.dims.x * (i.y + P.dims.y * i.z)];
}

@compute @workgroup_size(8, 8, 4)
fn polygonise(@builtin(global_invocation_id) cell: vec3u) {
  if any(cell + vec3u(1u) >= P.dims) {
    return;
  }
  var v: array<f32, 8>;
  var cube = 0u;
  for (var c = 0u; c < 8u; c++) {
    v[c] = value_at(cell + CORNERS[c]);
    if v[c] < 0.0 {
      cube |= 1u << c;
    }
  }
  if cube == 0u || cube == 255u {
    return;
  }
  let row = i32(cube) * 16;
  var count = 0u;
  while count < 15u && tri_table[row + i32(count)] >= 0 {
    count++;
  }
  let first = atomicAdd(&written, count / 3u);
  if first + count / 3u > P.capacity {
    return;
  }
  for (var n = 0u; n < count; n++) {
    let edge = EDGES[tri_table[row + i32(n)]];
    let a = CORNERS[edge.x];
    let b = CORNERS[edge.y];
    let t = v[edge.x] / (v[edge.x] - v[edge.y]);
    let g = vec3f(cell + a) + t * vec3f(b - a);
    let p = P.origin + vec3f(g.x, g.y, g.z + f32(P.z0)) * P.h;
    let o = (first * 3u + n) * 3u;
    triangles[o] = p.x;
    triangles[o + 1u] = p.y;
    triangles[o + 2u] = p.z;
  }
}
