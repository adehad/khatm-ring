import * as THREE from "three";
import { XzReadableStream } from "xz-decompress";
import { Group, parseRingStl, type RingInfo } from "./stl.ts";

// index.html preloads the model; the build renames it after its content hash.
function modelUrl(): string {
  const link = document.querySelector<HTMLLinkElement>("link#model");
  if (link === null) throw new Error('index.html needs <link id="model">');
  return link.href;
}

export interface LoadedRing {
  readonly mesh: THREE.Mesh;
  readonly info: RingInfo;
  readonly stl: ArrayBuffer;
}

// Colours and finishes match the materials the Blender build assigns.
function materials(): THREE.MeshStandardMaterial[] {
  const silver = new THREE.MeshStandardMaterial({ metalness: 1, roughness: 0.2, envMapIntensity: 1.8 });
  silver.color.setRGB(0.92, 0.92, 0.9);
  const oxide = new THREE.MeshStandardMaterial({ metalness: 0, roughness: 0.85 });
  oxide.color.setRGB(0.03, 0.025, 0.02);
  const slots: THREE.MeshStandardMaterial[] = [];
  slots[Group.Silver] = silver;
  slots[Group.Field] = oxide;
  return slots;
}

function readWithProgress(response: Response, onProgress: (fraction: number) => void): Response {
  const total = Number(response.headers.get("content-length") ?? 0);
  const body = response.body;
  if (body === null || total === 0) return response;
  let loaded = 0;
  const counted = body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        loaded += chunk.byteLength;
        onProgress(loaded / total);
        controller.enqueue(chunk);
      },
    }),
  );
  return new Response(counted);
}

export async function loadRing(onProgress: (fraction: number) => void): Promise<LoadedRing> {
  const url = modelUrl();
  const response = await fetch(url);
  if (!response.ok || response.body === null) throw new Error(`${url}: HTTP ${response.status}`);
  const counted = readWithProgress(response, onProgress);
  if (counted.body === null) throw new Error(`${url}: empty response`);
  const stl = await new Response(new XzReadableStream(counted.body)).arrayBuffer();
  const { geometry, info } = parseRingStl(stl);
  return { mesh: new THREE.Mesh(geometry, materials()), info, stl };
}
