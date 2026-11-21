import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { createDesert } from "./desert.ts";
import { placeIcons } from "./icons.ts";
import { loadRing, type LoadedRing } from "./model.ts";
import { createStars, Sky, type SkyColors } from "./sky.ts";
import { studioEnvironment } from "./studio.ts";
import { initThemeToggle, resolvedScheme, type Scheme } from "./theme.ts";
import { CameraFlight, isViewName, VIEWS } from "./views.ts";

const REPO_URL = "https://github.com/adehad/khatm-ring";
const FLOAT_MM = 10;
const CAMERA_CLEARANCE_MM = 2;

interface Palette extends SkyColors {
  readonly sand: THREE.ColorRepresentation;
  readonly hemiSky: THREE.ColorRepresentation;
  readonly hemiGround: THREE.ColorRepresentation;
  readonly hemi: number;
  readonly env: number;
  readonly exposure: number;
  readonly stars: boolean;
}

const PALETTES: Readonly<Record<Scheme, Palette>> = {
  light: {
    skyTop: 0xe8c47e,
    horizon: 0xf8e2b4,
    glow: 0xfff0c0,
    sand: 0xd9b27a,
    hemiSky: 0xfff1d0,
    hemiGround: 0xc89a5c,
    hemi: 1.3,
    env: 1.0,
    exposure: 1.0,
    stars: false,
  },
  dark: {
    skyTop: 0x0b0d1c,
    horizon: 0x3a2a2e,
    glow: 0xb07a3a,
    sand: 0x3e3226,
    hemiSky: 0x2c3050,
    hemiGround: 0x1c140c,
    hemi: 0.5,
    env: 0.75,
    exposure: 0.85,
    stars: true,
  },
};

function byId<T extends HTMLElement>(id: string, type: new () => T): T {
  const el = document.querySelector(`#${id}`);
  if (!(el instanceof type)) throw new TypeError(`#${id} is missing or not a ${type.name}`);
  return el;
}

const canvas = byId("scene", HTMLCanvasElement);
const status = byId("status", HTMLParagraphElement);
const details = byId("details", HTMLParagraphElement);
const build = byId("build", HTMLParagraphElement);
const spin = byId("spin", HTMLButtonElement);
const download = byId("download", HTMLButtonElement);

placeIcons();

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;

const scene = new THREE.Scene();
scene.environment = studioEnvironment(renderer);
const fog = new THREE.Fog(0xffffff, 250, 2600);
scene.fog = fog;

const camera = new THREE.PerspectiveCamera(32, 1, 1, 6000);
camera.position.set(...VIEWS["three-quarter"]);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.minDistance = 35;
controls.maxDistance = 260;
controls.maxPolarAngle = THREE.MathUtils.degToRad(104);
controls.autoRotate = true;
controls.autoRotateSpeed = 0.8;

const sky = new Sky();
const stars = createStars();
const desert = createDesert(renderer);
const hemi = new THREE.HemisphereLight();
scene.add(sky, stars, desert.group, hemi);

// The sand sits FLOAT_MM below the ring; until the ring loads, below its usual size.
let groundY = -12 - FLOAT_MM;
desert.group.position.y = groundY;

function applyPalette(): void {
  const p = PALETTES[resolvedScheme()];
  sky.setColors(p);
  fog.color.set(p.horizon);
  desert.material.color.set(p.sand);
  hemi.color.set(p.hemiSky);
  hemi.groundColor.set(p.hemiGround);
  hemi.intensity = p.hemi;
  scene.environmentIntensity = p.env;
  renderer.toneMappingExposure = p.exposure;
  stars.visible = p.stars;
}
initThemeToggle(byId("theme", HTMLButtonElement), applyPalette);
applyPalette();

function setSpin(on: boolean): void {
  controls.autoRotate = on;
  spin.setAttribute("aria-pressed", String(on));
}
if (matchMedia("(prefers-reduced-motion: reduce)").matches) setSpin(false);
spin.addEventListener("click", () => {
  setSpin(!controls.autoRotate);
});
canvas.addEventListener("pointerdown", () => {
  setSpin(false);
});

const flight = new CameraFlight(camera, controls);
for (const button of document.querySelectorAll<HTMLButtonElement>("[data-view]")) {
  const view = button.dataset["view"];
  if (!isViewName(view)) throw new Error(`unknown view ${view ?? "(none)"}`);
  button.addEventListener("click", () => {
    setSpin(false);
    flight.to(view);
  });
}

// Links the build commit the model came from. A "+" means it was built with
// uncommitted changes, so no commit matches it exactly.
function showBuild(commit: string): void {
  const sha = commit.replace(/\+$/u, "");
  const link = document.createElement("a");
  link.href = `${REPO_URL}/commit/${sha}`;
  link.textContent = sha;
  build.replaceChildren("Built from ", link, sha === commit ? "" : " with local changes");
}

function showRing({ mesh, info, stl }: LoadedRing): void {
  scene.add(mesh);
  const box = mesh.geometry.boundingBox;
  if (box !== null) {
    groundY = box.min.y - FLOAT_MM;
    desert.group.position.y = groundY;
  }
  details.textContent = `${info.grams.toFixed(2)} g · US ${info.us} · UK ${info.uk} · ${info.insideDiameter.toFixed(1)} mm inside`;
  showBuild(info.build);
  const url = URL.createObjectURL(new Blob([stl], { type: "model/stl" }));
  download.addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = url;
    a.download = "khatm-ring.stl";
    a.click();
  });
  download.disabled = false;
  status.textContent = "";
}

try {
  showRing(
    await loadRing((fraction) => {
      status.textContent = `Loading model… ${Math.round(fraction * 100)}%`;
    }),
  );
} catch (error: unknown) {
  status.textContent = "Could not load the model.";
  console.error(error);
}

function resize(): void {
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
  camera.aspect = canvas.clientWidth / canvas.clientHeight;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

let last = performance.now();
renderer.setAnimationLoop((now: number) => {
  const dt = (now - last) / 1000;
  last = now;
  flight.update(dt);
  controls.update(dt);
  // Orbiting low and far would put the camera under the dunes.
  camera.position.y = Math.max(camera.position.y, groundY + CAMERA_CLEARANCE_MM);
  renderer.render(scene, camera);
});
