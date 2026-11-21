import * as THREE from "three";

export interface SkyColors {
  readonly skyTop: THREE.ColorRepresentation;
  readonly horizon: THREE.ColorRepresentation;
  readonly glow: THREE.ColorRepresentation;
}

interface SkyUniforms {
  readonly top: THREE.IUniform<THREE.Color>;
  readonly horizon: THREE.IUniform<THREE.Color>;
  readonly glow: THREE.IUniform<THREE.Color>;
  readonly sun: THREE.IUniform<THREE.Vector3>;
}

export class Sky extends THREE.Mesh<THREE.SphereGeometry, THREE.ShaderMaterial> {
  private readonly uniforms: SkyUniforms;

  constructor(radius = 5000) {
    const uniforms: SkyUniforms = {
      top: { value: new THREE.Color() },
      horizon: { value: new THREE.Color() },
      glow: { value: new THREE.Color() },
      sun: { value: new THREE.Vector3(-0.6, 0.25, -0.75).normalize() },
    };
    super(
      new THREE.SphereGeometry(radius, 48, 24),
      new THREE.ShaderMaterial({
        side: THREE.BackSide,
        depthWrite: false,
        fog: false,
        uniforms: { ...uniforms },
        vertexShader: `
          varying vec3 vDir;
          void main() {
            vDir = normalize(position);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }`,
        fragmentShader: `
          uniform vec3 top, horizon, glow, sun;
          varying vec3 vDir;
          void main() {
            float h = clamp(vDir.y, 0.0, 1.0);
            vec3 c = mix(horizon, top, pow(h, 0.55));
            float g = pow(max(dot(vDir, sun), 0.0), 6.0);
            c = mix(c, glow, g * 0.7);
            gl_FragColor = vec4(c, 1.0);
            #include <tonemapping_fragment>
            #include <colorspace_fragment>
          }`,
      }),
    );
    this.uniforms = uniforms;
  }

  setColors({ skyTop, horizon, glow }: SkyColors): void {
    this.uniforms.top.value.set(skyTop);
    this.uniforms.horizon.value.set(horizon);
    this.uniforms.glow.value.set(glow);
  }
}

export function createStars(count = 1800, radius = 4800): THREE.Points {
  const pts: number[] = [];
  for (let i = 0; i < count; i++) {
    const y = 0.08 + Math.random() * 0.92;
    const a = Math.random() * Math.PI * 2;
    const r = Math.sqrt(1 - y * y);
    pts.push(Math.cos(a) * r * radius, y * radius, Math.sin(a) * r * radius);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return new THREE.Points(
    g,
    new THREE.PointsMaterial({ color: 0xfff4dc, size: 1.6, sizeAttenuation: false, fog: false }),
  );
}
