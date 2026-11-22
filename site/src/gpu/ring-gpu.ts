import { triTable } from "three/addons/objects/MarchingCubes.js";
import type { RingSpec } from "../ring-spec.ts";
import { ringGrid, sizeValues, wgslConstants, type Grid, type RingShape } from "./grid.ts";
import marchingWgsl from "./marching.wgsl" with { type: "text" };
import paramsWgsl from "./params.wgsl" with { type: "text" };
import ringWgsl from "./ring.wgsl" with { type: "text" };

// params.wgsl's Params, rounded up to a multiple of 16 bytes.
const PARAMS_BYTES = 80;
const FLOATS_PER_TRIANGLE = 9;
const BYTES_PER_TRIANGLE = FLOATS_PER_TRIANGLE * 4;
const SAMPLE_GROUP = 64;
const GRID_GROUP = [8, 8, 4] as const;
const SLAB_BYTES = 48 * 1024 * 1024;
const FIRST_CAPACITY = 400_000;
const COPY_ALIGN = 4;
const GROWTH = 1.5;

interface SlabBuffers {
  readonly values: GPUBuffer;
  readonly written: GPUBuffer;
  triangles: GPUBuffer;
  /** Triangles that fit in `triangles`. */
  capacity: number;
}

function groups(n: number, size: number): number {
  return Math.ceil(n / size);
}

export class RingGpu {
  private readonly params: GPUBuffer;
  private readonly faces: GPUTexture;
  private readonly sampler: GPUComputePipeline;
  private readonly fieldPipeline: GPUComputePipeline;
  private readonly volumePipeline: GPUComputePipeline;
  private readonly marching: GPUComputePipeline;
  private readonly table: GPUBuffer;

  private constructor(
    private readonly device: GPUDevice,
    private readonly spec: RingSpec,
    ring: GPUShaderModule,
    marching: GPUShaderModule,
  ) {
    this.params = device.createBuffer({
      size: PARAMS_BYTES,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });
    this.faces = device.createTexture({
      size: [spec.rasterCols, spec.rasterRows, 2],
      format: "r16float",
      usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST,
    });
    device.queue.writeTexture(
      { texture: this.faces },
      spec.rasters,
      { bytesPerRow: spec.rasterCols * 2, rowsPerImage: spec.rasterRows },
      [spec.rasterCols, spec.rasterRows, 2],
    );
    const pipeline = (module: GPUShaderModule, entryPoint: string): GPUComputePipeline =>
      device.createComputePipeline({ layout: "auto", compute: { module, entryPoint } });
    this.sampler = pipeline(ring, "sample");
    this.fieldPipeline = pipeline(ring, "field");
    this.volumePipeline = pipeline(ring, "volume");
    this.marching = pipeline(marching, "polygonise");
    this.table = this.upload(new Int32Array(triTable), GPUBufferUsage.STORAGE);
  }

  static async create(spec: RingSpec, adapterOptions: GPURequestAdapterOptions = {}): Promise<RingGpu> {
    const adapter = await navigator.gpu?.requestAdapter(adapterOptions);
    if (adapter === undefined || adapter === null) throw new Error("this browser has no WebGPU adapter");
    const device = await adapter.requestDevice({
      requiredLimits: {
        maxStorageBufferBindingSize: adapter.limits.maxStorageBufferBindingSize,
        maxBufferSize: adapter.limits.maxBufferSize,
      },
    });
    const compile = async (code: string): Promise<GPUShaderModule> => {
      const module = device.createShaderModule({ code });
      const info = await module.getCompilationInfo();
      const errors = info.messages.filter((m) => m.type === "error");
      if (errors.length > 0) {
        throw new Error(
          errors.map((m) => `WGSL ${String(m.lineNum)}:${String(m.linePos)} ${m.message}`).join("\n"),
        );
      }
      return module;
    };
    const [ring, marching] = await Promise.all([
      compile([wgslConstants(spec), paramsWgsl, ringWgsl].join("\n")),
      compile([paramsWgsl, marchingWgsl].join("\n")),
    ]);
    return new RingGpu(device, spec, ring, marching);
  }

  destroy(): void {
    this.device.destroy();
  }

  private upload(data: Float32Array | Int32Array, usage: number): GPUBuffer {
    const buffer = this.device.createBuffer({
      size: data.byteLength,
      usage: usage | GPUBufferUsage.COPY_DST,
    });
    this.device.queue.writeBuffer(buffer, 0, data);
    return buffer;
  }

  private storage(bytes: number): GPUBuffer {
    return this.device.createBuffer({
      size: Math.max(bytes, COPY_ALIGN),
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
    });
  }

  private setParams(
    shape: RingShape,
    grid: Grid,
    z0: number,
    layers: number,
    extra: { capacity?: number; points?: number },
  ): void {
    const size = sizeValues(this.spec, shape.insideD);
    const data = new ArrayBuffer(PARAMS_BYTES);
    const f = new Float32Array(data);
    const u = new Uint32Array(data);
    f.set(grid.origin, 0);
    f[3] = grid.h;
    u.set([grid.dims[0], grid.dims[1], layers, z0], 4);
    f.set([size.rFinger, size.rSaddle, size.zTop, size.zField, shape.wEnd, shape.tEnd], 8);
    u[14] = extra.capacity ?? 0;
    u[15] = extra.points ?? 0;
    f[16] = shape.plateExtra;
    this.device.queue.writeBuffer(this.params, 0, data);
  }

  private bind(
    pipeline: GPUComputePipeline,
    buffers: Readonly<Record<number, GPUBuffer>>,
    faces: boolean,
  ): GPUBindGroup {
    const entries: GPUBindGroupEntry[] = [{ binding: 0, resource: { buffer: this.params } }];
    if (faces) entries.push({ binding: 1, resource: this.faces.createView() });
    for (const [binding, buffer] of Object.entries(buffers))
      entries.push({ binding: Number(binding), resource: { buffer } });
    return this.device.createBindGroup({ layout: pipeline.getBindGroupLayout(0), entries });
  }

  private dispatch(
    pipeline: GPUComputePipeline,
    group: GPUBindGroup,
    counts: readonly [number, number, number],
  ): void {
    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginComputePass();
    pass.setPipeline(pipeline);
    pass.setBindGroup(0, group);
    pass.dispatchWorkgroups(...counts);
    pass.end();
    this.device.queue.submit([encoder.finish()]);
  }

  private async read(source: GPUBuffer, bytes: number): Promise<ArrayBuffer> {
    const size = Math.max(Math.ceil(bytes / COPY_ALIGN) * COPY_ALIGN, COPY_ALIGN);
    const staging = this.device.createBuffer({
      size,
      usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
    });
    const encoder = this.device.createCommandEncoder();
    encoder.copyBufferToBuffer(source, 0, staging, 0, size);
    this.device.queue.submit([encoder.finish()]);
    await staging.mapAsync(GPUMapMode.READ);
    const copy = staging.getMappedRange().slice(0, bytes);
    staging.destroy();
    return copy;
  }

  /** The field at each x, y, z triple. */
  async sample(shape: RingShape, xyz: Float32Array): Promise<Float32Array> {
    const n = xyz.length / 3;
    const points = this.upload(xyz, GPUBufferUsage.STORAGE);
    const results = this.storage(n * 4);
    this.setParams(shape, ringGrid(this.spec, shape.insideD, 1), 0, 1, { points: n });
    this.dispatch(this.sampler, this.bind(this.sampler, { 2: results, 3: points }, true), [
      groups(n, SAMPLE_GROUP),
      1,
      1,
    ]);
    const values = new Float32Array(await this.read(results, n * 4));
    points.destroy();
    results.destroy();
    return values;
  }

  /** Ring.volume_mm3: metal volume counted on a grid of spacing h. */
  async volume(shape: RingShape, h: number): Promise<number> {
    const grid = ringGrid(this.spec, shape.insideD, h);
    const counts = [
      groups(grid.dims[0], GRID_GROUP[0]),
      groups(grid.dims[1], GRID_GROUP[1]),
      groups(grid.dims[2], GRID_GROUP[2]),
    ] as const;
    const partials = counts[0] * counts[1] * counts[2];
    const results = this.storage(partials * 4);
    this.setParams(shape, grid, 0, grid.dims[2], {});
    this.dispatch(this.volumePipeline, this.bind(this.volumePipeline, { 2: results }, true), counts);
    const sums = new Float32Array(await this.read(results, partials * 4));
    results.destroy();
    let total = 0;
    for (const s of sums) total += s;
    return total * h ** 3;
  }

  /**
   * Marching cubes on a grid of spacing h, a slab of z layers at a time, as a
   * triangle soup: nine floats per triangle.
   */
  async mesh(shape: RingShape, h: number, onProgress: (fraction: number) => void): Promise<Float32Array> {
    const grid = ringGrid(this.spec, shape.insideD, h);
    const [nx, ny, nz] = grid.dims;
    const slab = Math.max(1, Math.min(nz - 1, Math.floor(SLAB_BYTES / (nx * ny * 4)) - 1));
    const buffers: SlabBuffers = {
      values: this.storage(nx * ny * (slab + 1) * 4),
      written: this.storage(4),
      triangles: this.storage(FIRST_CAPACITY * BYTES_PER_TRIANGLE),
      capacity: FIRST_CAPACITY,
    };
    const chunks: Float32Array[] = [];
    for (let z0 = 0; z0 < nz - 1; z0 += slab) {
      const layers = Math.min(slab + 1, nz - z0);
      // oxlint-disable-next-line no-await-in-loop -- the slabs share one set of buffers
      chunks.push(await this.meshSlab(buffers, shape, grid, z0, layers));
      onProgress(Math.min(1, (z0 + slab) / (nz - 1)));
    }
    buffers.values.destroy();
    buffers.written.destroy();
    buffers.triangles.destroy();

    const soup = new Float32Array(chunks.reduce((n, chunk) => n + chunk.length, 0));
    let offset = 0;
    for (const chunk of chunks) {
      soup.set(chunk, offset);
      offset += chunk.length;
    }
    return soup;
  }

  private async meshSlab(
    buffers: SlabBuffers,
    shape: RingShape,
    grid: Grid,
    z0: number,
    layers: number,
  ): Promise<Float32Array> {
    const dims = [grid.dims[0], grid.dims[1], layers] as const;
    this.setParams(shape, grid, z0, layers, { capacity: buffers.capacity });
    this.dispatch(this.fieldPipeline, this.bind(this.fieldPipeline, { 2: buffers.values }, true), [
      groups(dims[0], GRID_GROUP[0]),
      groups(dims[1], GRID_GROUP[1]),
      groups(dims[2], GRID_GROUP[2]),
    ]);
    let count = await this.polygonise(buffers, dims);
    if (count > buffers.capacity) {
      buffers.capacity = Math.ceil(count * GROWTH);
      buffers.triangles.destroy();
      buffers.triangles = this.storage(buffers.capacity * BYTES_PER_TRIANGLE);
      this.setParams(shape, grid, z0, layers, { capacity: buffers.capacity });
      count = await this.polygonise(buffers, dims);
    }
    if (count === 0) return new Float32Array(0);
    return new Float32Array(await this.read(buffers.triangles, count * BYTES_PER_TRIANGLE));
  }

  private async polygonise(buffers: SlabBuffers, dims: readonly [number, number, number]): Promise<number> {
    this.device.queue.writeBuffer(buffers.written, 0, new Uint32Array([0]));
    const group = this.bind(
      this.marching,
      { 1: buffers.values, 2: this.table, 3: buffers.written, 4: buffers.triangles },
      false,
    );
    this.dispatch(this.marching, group, [
      groups(dims[0], GRID_GROUP[0]),
      groups(dims[1], GRID_GROUP[1]),
      groups(dims[2], GRID_GROUP[2]),
    ]);
    return new Uint32Array(await this.read(buffers.written, 4))[0] ?? 0;
  }
}
