import * as THREE from "three";
import type { OrbitControls } from "three/addons/controls/OrbitControls.js";

// Camera positions around a target at the ring's centre, in millimetres.
export const VIEWS = {
  "three-quarter": [64, 25, 78],
  face: [0, 95, 0.01],
  front: [0, 6, 95],
  side: [95, 6, 0],
  underside: [55, -17, 45],
} as const satisfies Record<string, THREE.Vector3Tuple>;

export type ViewName = keyof typeof VIEWS;

export function isViewName(name: string | undefined): name is ViewName {
  return name !== undefined && Object.hasOwn(VIEWS, name);
}

interface Flight {
  readonly from: THREE.Spherical;
  readonly to: THREE.Spherical;
  t: number;
}

// Glides the camera along a sphere about the target, taking the short way round.
export class CameraFlight {
  private flight: Flight | null = null;

  constructor(
    private readonly camera: THREE.PerspectiveCamera,
    private readonly controls: OrbitControls,
    private readonly seconds = 0.9,
  ) {}

  to(name: ViewName): void {
    const target = this.controls.target;
    this.flight = {
      from: new THREE.Spherical().setFromVector3(this.camera.position.clone().sub(target)),
      to: new THREE.Spherical().setFromVector3(new THREE.Vector3(...VIEWS[name]).sub(target)),
      t: 0,
    };
  }

  update(dt: number): void {
    const f = this.flight;
    if (f === null) return;
    f.t = Math.min(f.t + dt / this.seconds, 1);
    const k = 1 - (1 - f.t) ** 3;
    const turn = f.to.theta - f.from.theta;
    const dTheta = Math.atan2(Math.sin(turn), Math.cos(turn));
    const s = new THREE.Spherical(
      f.from.radius + (f.to.radius - f.from.radius) * k,
      f.from.phi + (f.to.phi - f.from.phi) * k,
      f.from.theta + dTheta * k,
    );
    this.camera.position.setFromSpherical(s).add(this.controls.target);
    if (f.t === 1) this.flight = null;
  }
}
