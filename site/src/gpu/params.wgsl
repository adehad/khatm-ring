// What changes between dispatches: the grid, the ring size, the band's ends
// and the plate's extra thickness.
// The ring size values are those ring_sdf.set_size() computes.
struct Params {
  origin: vec3f,
  h: f32,
  dims: vec3u,
  z0: u32,
  r_finger: f32,
  r_saddle: f32,
  z_top: f32,
  z_field: f32,
  w_end: f32,
  t_end: f32,
  capacity: u32,
  points: u32,
  plate_extra: f32,
}
