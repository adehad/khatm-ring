// The ring's signed distance field: a line-for-line port of ring_sdf.py on the
// build branch. Millimetres, finger along +Y, face up +Z, negative inside.
// The named constants (FACE_D, BAND_W_ROOT, ...) are prepended from
// ring-sdf.json; the bare numbers below are the ones written inline in the
// Python. Params comes from params.wgsl. The parity test checks this file
// against that module.

@group(0) @binding(0) var<uniform> P: Params;
// Layer 0 is the field outline, layer 1 the letters: Field2D.sdf rasters,
// row 0 at +FACE_D/2.
@group(0) @binding(1) var faces: texture_2d_array<f32>;
@group(0) @binding(2) var<storage, read_write> results: array<f32>;
@group(0) @binding(3) var<storage, read> points: array<f32>;

fn smin(a: f32, b: f32, k_in: f32) -> f32 {
  let k = max(k_in, 1e-5);
  let h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
  return b + (a - b) * h - k * h * (1.0 - h);
}

fn smax(a: f32, b: f32, k: f32) -> f32 {
  return -smin(-a, -b, k);
}

fn smooth_step(x_in: f32) -> f32 {
  let x = clamp(x_in, 0.0, 1.0);
  return x * x * (3.0 - 2.0 * x);
}

fn smoother_step(x_in: f32) -> f32 {
  let x = clamp(x_in, 0.0, 1.0);
  return x * x * x * (x * (6.0 * x - 15.0) + 10.0);
}

fn texel(layer: i32, col: i32, row: i32) -> f32 {
  return textureLoad(faces, vec2i(col, row), layer, 0).r;
}

// Field2D.__call__: bilinear, clamped at the edges, plus the distance past the
// raster so the field stays a bound outside it.
fn face(layer: i32, u: f32, v: f32) -> f32 {
  let size = vec2f(textureDimensions(faces));
  let cols = (u + FACE_D / 2.0) / RASTER;
  let rows = (FACE_D / 2.0 - v) / RASTER;
  let c = clamp(cols, 0.0, size.x - 1.0);
  let r = clamp(rows, 0.0, size.y - 1.0);
  let c0 = min(i32(floor(c)), i32(size.x) - 2);
  let r0 = min(i32(floor(r)), i32(size.y) - 2);
  let fc = c - f32(c0);
  let fr = r - f32(r0);
  let top = mix(texel(layer, c0, r0), texel(layer, c0 + 1, r0), fc);
  let bottom = mix(texel(layer, c0, r0 + 1), texel(layer, c0 + 1, r0 + 1), fc);
  let d = mix(top, bottom, fr);
  let over = max(max(max(-cols, cols - (size.x - 1.0)), max(-rows, rows - (size.y - 1.0))), 0.0) * RASTER;
  return d + over;
}

// Radius of the head's wall at height z, and its slope.
fn head_radius(z: f32) -> vec2f {
  let u = clamp((P.z_top - CROWN_R - z) / HEAD_DROP, 0.0, 1.0);
  return vec2f(FACE_D / 2.0 + HEAD_FLARE * u * u, 2.0 * HEAD_FLARE * u / HEAD_DROP);
}

// Where the head's wall, at its widest, meets the band's outside: (x, z).
fn head_join() -> vec2f {
  let r_wall = FACE_D / 2.0 + HEAD_FLARE;
  let r_out = P.r_finger + BAND_T_ROOT;
  return vec2f(r_wall, sqrt(max(r_out * r_out - r_wall * r_wall, 0.0)));
}

// The band's width at theta degrees, before its tip and wave, and how far
// through its flare it is.
fn band_width(theta: f32) -> vec2f {
  let u = (clamp(theta, ARM_START_DEG, ARM_END_DEG) - ARM_START_DEG) / (ARM_END_DEG - ARM_START_DEG);
  let s = smoother_step(u / FLARE_SPAN);
  return vec2f(BAND_W_ROOT + (P.w_end - BAND_W_ROOT) * s, s);
}

fn head(x: f32, y: f32, rho: f32, z: f32, rf: f32) -> f32 {
  let wall = head_radius(z);
  let qx = (rho - wall.x) / sqrt(1.0 + wall.y * wall.y) + CROWN_R;
  let qz = z - P.z_top + CROWN_R;
  var d = min(max(qx, qz), 0.0) + length(max(vec2f(qx, qz), vec2f(0.0))) - CROWN_R;
  let y0 = BAND_W_ROOT / 2.0 - 0.6;
  let u = clamp((abs(y) - y0) / (FACE_D / 2.0 - y0), 0.0, 1.0);
  // pow(0, p) is undefined in WGSL.
  let rise = select(0.0, pow(u, BOAT_POWER), u > 0.0);
  let floor_z = P.r_saddle + (P.z_top - BOAT_EDGE - P.r_saddle) * rise;
  d = smax(d, floor_z - rf, select(K_SEAT, K_BOAT, u > 0.0));
  let theta = degrees(atan2(abs(x), z));
  let off = 1.0 - smooth_step((theta - HEAD_SIDE_START_DEG) / (HEAD_SIDE_END_DEG - HEAD_SIDE_START_DEG));
  let reach = band_width(theta).x / 2.0 - HEAD_SIDE_INSET
    + HEAD_SIDE_FLARE * max(rf - P.r_finger - BAND_T_ROOT, 0.0) + off * FACE_D;
  d = smax(d, abs(y) - reach, K_HEAD_SIDE);
  let z_join = head_join().y;
  return max(d, z_join - 1.0 - z);
}

fn cavity(rho: f32, z: f32) -> f32 {
  let wall = head_radius(z);
  var r = wall.x;
  var slope = wall.y;
  let x_wall = FACE_D / 2.0 + HEAD_FLARE - WALL_T;
  let x_meet = x_wall + CAVITY_LEAN;
  var z_meet = sqrt(max(P.r_finger * P.r_finger - x_meet * x_meet, 0.0));
  if z_meet > 0.0 {
    let span = 2.0 * CAVITY_LEAN * x_meet / z_meet;
    let u = clamp((z_meet + span - z) / span, 0.0, 1.0);
    r = r + CAVITY_LEAN * u * u;
    slope = slope + 2.0 * CAVITY_LEAN * u / span;
  } else {
    z_meet = CAVITY_TUCK_Z;
    let x_hole = sqrt(P.r_finger * P.r_finger - z_meet * z_meet);
    let shift = x_hole - x_wall;
    let bend = CAVITY_TUCK * z_meet / x_hole;
    let u = clamp((z_meet + CAVITY_TUCK - z) / CAVITY_TUCK, 0.0, 1.0);
    r = r + shift * u * u * (3.0 - 2.0 * u) + bend * u * u * (u - 1.0);
    slope = slope + abs(shift * 6.0 * u * (1.0 - u) + bend * u * (3.0 * u - 2.0)) / CAVITY_TUCK;
  }
  var walls = (rho - (r - WALL_T)) / sqrt(1.0 + slope * slope);
  walls = max(walls, z_meet - 0.5 - z);
  let r_c = FACE_D / 2.0 - WALL_T;
  let dome = (PLATE_RIM - PLATE_CENTRE) / (r_c * r_c);
  let ceiling = P.z_field - PLATE_CENTRE - dome * rho * rho;
  let under = (z - ceiling) / sqrt(1.0 + (2.0 * dome * rho) * (2.0 * dome * rho));
  return smax(walls, under, K_CAVITY_CORNER);
}

// One arm: distance, and the angle round the finger in degrees, [0, 360).
fn arm(x: f32, y: f32, z: f32, side: f32, rides_over: bool, phase: f32) -> vec2f {
  let rf = length(vec2f(x, z));
  let raw = degrees(atan2(side * x, z));
  let theta = raw - 360.0 * floor(raw / 360.0);
  let th = clamp(theta, ARM_START_DEG, ARM_END_DEG);
  let band = band_width(theta);
  let s = band.y;
  var w = band.x;
  var t = BAND_T_ROOT + (P.t_end - BAND_T_ROOT) * s;
  let tip = smooth_step((th - (ARM_END_DEG - TIP_TAPER_DEG)) / TIP_TAPER_DEG);
  w = w + (TIP_W - w) * tip;
  t = t + (TIP_T - t) * tip;
  w = w * (1.0 + BAND_WAVE * sin(radians(2.5 * th) + phase));
  var r_in = P.r_finger;
  if rides_over {
    r_in = r_in + (P.t_end + OVERLAP_GAP) * smooth_step((th - RIDE_START_DEG) / (RIDE_END_DEG - RIDE_START_DEG));
  }

  var gap = 0.0;
  if theta > ARM_END_DEG {
    gap = theta - ARM_END_DEG;
  } else if theta < ARM_START_DEG {
    gap = ARM_START_DEG - theta;
  }
  let arc = radians(gap) * (r_in + t / 2.0);
  let yy = length(vec2f(y, arc));

  let c = min(BAND_CORNER, t / 2.0 - 0.05);
  let qx = abs(rf - (r_in + t / 2.0)) - (t / 2.0 - c);
  let qy = yy - (w / 2.0 - c);
  let d = length(max(vec2f(qx, qy), vec2f(0.0))) + min(max(qx, qy), 0.0) - c;
  return vec2f(d, theta);
}

fn ring(p: vec3f) -> f32 {
  let rho = length(p.xy);
  let rf = length(p.xz);

  var body = head(p.x, p.y, rho, p.z, rf);
  let join = head_join();
  let fade_deg = degrees(atan2(join.x, join.y));
  for (var i = 0; i < 2; i++) {
    let first = i == 0;
    let a = arm(p.x, p.y, p.z, select(-1.0, 1.0, first), !first, select(1.9, 0.0, first));
    var k = K_SHOULDER * (1.0 - smooth_step((a.y - fade_deg) / 35.0)) * smooth_step((rf - P.r_finger) / BAND_T_ROOT);
    k = select(k, 0.0, a.y > 300.0);
    body = smin(body, a.x, k);
  }
  body = smax(body, -cavity(rho, p.z), K_LIP);

  let recess = max(P.z_field - p.z, (face(0, p.x, p.y) - (p.z - P.z_field)) * 0.7071);
  body = smax(body, -recess, K_RECESS);

  let qx = face(1, p.x, p.y) + LETTER_ROUND;
  let qz = p.z - (P.z_top - LETTER_ROUND);
  var letters = min(max(qx, qz), 0.0) + length(max(vec2f(qx, qz), vec2f(0.0))) - LETTER_ROUND;
  letters = max(letters, (P.z_field - 0.15) - p.z);
  return smin(body, letters, K_LETTER);
}

fn grid_point(i: vec3u) -> vec3f {
  return P.origin + vec3f(f32(i.x), f32(i.y), f32(i.z + P.z0)) * P.h;
}

// The field at each x, y, z triple in `points`.
@compute @workgroup_size(64)
fn sample(@builtin(global_invocation_id) id: vec3u) {
  if id.x >= P.points {
    return;
  }
  let o = id.x * 3u;
  results[id.x] = ring(vec3f(points[o], points[o + 1u], points[o + 2u]));
}

// The field on a slab of the grid, x fastest.
@compute @workgroup_size(8, 8, 4)
fn field(@builtin(global_invocation_id) id: vec3u) {
  if any(id >= P.dims) {
    return;
  }
  results[id.x + P.dims.x * (id.y + P.dims.y * id.z)] = ring(grid_point(id));
}

var<workgroup> partial: array<f32, 256>;

// Ring.volume_mm3 without the final scale: each grid point counts as the
// fraction of its voxel inside, clip(0.5 - d / h, 0, 1). One sum per workgroup.
@compute @workgroup_size(8, 8, 4)
fn volume(
  @builtin(global_invocation_id) id: vec3u,
  @builtin(local_invocation_index) lane: u32,
  @builtin(workgroup_id) group: vec3u,
  @builtin(num_workgroups) groups: vec3u,
) {
  var inside = 0.0;
  if all(id < P.dims) {
    inside = clamp(0.5 - ring(grid_point(id)) / P.h, 0.0, 1.0);
  }
  partial[lane] = inside;
  for (var stride = 128u; stride > 0u; stride >>= 1u) {
    workgroupBarrier();
    if lane < stride {
      partial[lane] += partial[lane + stride];
    }
  }
  if lane == 0u {
    results[group.x + groups.x * (group.y + groups.y * group.z)] = partial[0];
  }
}
