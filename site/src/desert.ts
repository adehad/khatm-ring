import * as THREE from "three";

// Units are millimetres. Wind ripples near the ring, dunes further out, and a
// flat patch under the ring for its shadow.
const FLAT_R = 14;
const { smoothstep } = THREE.MathUtils;

function hash(x: number, y: number): number {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s);
}

function noise(x: number, y: number): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const xf = x - xi;
  const yf = y - yi;
  const u = xf * xf * (3 - 2 * xf);
  const v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi);
  const b = hash(xi + 1, yi);
  const c = hash(xi, yi + 1);
  const d = hash(xi + 1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}

function fbm(x: number, y: number): number {
  let s = 0;
  let amp = 0.5;
  let px = x;
  let py = y;
  for (let i = 0; i < 5; i++) {
    s += amp * noise(px, py);
    px *= 2.03;
    py *= 2.03;
    amp *= 0.5;
  }
  return s;
}

function sandHeight(x: number, z: number): number {
  const r = Math.hypot(x, z);
  const warp = fbm(x * 0.02, z * 0.02) * 6;
  const ripple = Math.sin((x * 0.83 + z * 0.56) * 0.55 + warp) * 0.7;
  const near = smoothstep(r, FLAT_R, 40);
  const dunes = (fbm(x * 0.004 + 3.1, z * 0.004) - 0.45) * Math.min(r * 0.12, 160);
  return ripple * near * (1 - smoothstep(r, 400, 900)) + dunes * smoothstep(r, 60, 400);
}

// A polar grid: fine under the ring, coarse at the horizon.
function desertGeometry(): THREE.BufferGeometry {
  const rings = 200;
  const spokes = 288;
  const rMin = 1.5;
  const rMax = 4500;
  const pos: number[] = [0, sandHeight(0, 0), 0];
  const uv: number[] = [0, 0];
  const idx: number[] = [];
  for (let i = 1; i <= rings; i++) {
    const r = rMin * (rMax / rMin) ** ((i - 1) / (rings - 1));
    for (let j = 0; j < spokes; j++) {
      const a = (j / spokes) * Math.PI * 2;
      const x = Math.cos(a) * r;
      const z = Math.sin(a) * r;
      pos.push(x, sandHeight(x, z), z);
      uv.push(x / 6, z / 6);
    }
  }
  for (let j = 0; j < spokes; j++) idx.push(0, 1 + ((j + 1) % spokes), 1 + j);
  for (let i = 1; i < rings; i++) {
    const a0 = 1 + (i - 1) * spokes;
    const a1 = 1 + i * spokes;
    for (let j = 0; j < spokes; j++) {
      const j1 = (j + 1) % spokes;
      idx.push(a0 + j, a0 + j1, a1 + j, a0 + j1, a1 + j1, a1 + j);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

function canvas2d(size: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const ctx = c.getContext("2d");
  if (ctx === null) throw new Error("no 2D canvas context");
  return [c, ctx];
}

function grainTexture(renderer: THREE.WebGLRenderer): THREE.CanvasTexture {
  const size = 256;
  const [c, ctx] = canvas2d(size);
  const img = ctx.createImageData(size, size);
  for (let i = 0; i < size * size; i++) {
    const v = 205 + Math.random() * 50;
    img.data.set([v, v, v, 255], i * 4);
  }
  ctx.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return t;
}

// A soft dark blot on the sand under the floating ring.
function blobShadow(width: number, depth: number): THREE.Mesh {
  const size = 128;
  const [c, ctx] = canvas2d(size);
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(0,0,0,0.4)");
  g.addColorStop(0.5, "rgba(0,0,0,0.16)");
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(width, depth),
    new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }),
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = 0.05;
  return mesh;
}

export interface Desert {
  readonly group: THREE.Group;
  readonly material: THREE.MeshStandardMaterial;
}

export function createDesert(renderer: THREE.WebGLRenderer): Desert {
  const grain = grainTexture(renderer);
  const material = new THREE.MeshStandardMaterial({
    roughness: 0.95,
    metalness: 0,
    map: grain,
    bumpMap: grain,
    bumpScale: 0.3,
    envMapIntensity: 0.6,
  });
  const group = new THREE.Group();
  group.add(new THREE.Mesh(desertGeometry(), material), blobShadow(34, 26));
  return { group, material };
}
