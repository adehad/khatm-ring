import * as THREE from "three";

// Warm softboxes on every side, overhead and below, baked into an environment
// map so the polished silver has gold-tinted light to reflect from any angle.
export function studioEnvironment(renderer: THREE.WebGLRenderer): THREE.Texture {
  const room = new THREE.Scene();
  room.background = new THREE.Color(0x5e5444);
  const quad = new THREE.PlaneGeometry(1, 1);
  const panel = (w: number, h: number, pos: THREE.Vector3Tuple, strength: number): void => {
    const material = new THREE.MeshBasicMaterial({
      color: new THREE.Color(1.0, 0.9, 0.68).multiplyScalar(strength),
      side: THREE.DoubleSide,
    });
    const p = new THREE.Mesh(quad, material);
    p.scale.set(w, h, 1);
    p.position.set(...pos);
    p.lookAt(0, 0, 0);
    room.add(p);
  };
  panel(6, 6, [0, 9, 0], 3.2);
  panel(6, 6, [0, -9, 0], 2.0);
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    panel(2.2, 5, [Math.cos(a) * 8, 2, Math.sin(a) * 8], i % 2 === 1 ? 1.6 : 2.6);
  }
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = pmrem.fromScene(room, 0.03).texture;
  pmrem.dispose();
  return env;
}
