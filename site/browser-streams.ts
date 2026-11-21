import type { BunPlugin } from "bun";

// xz-decompress requires Node's "stream/web" and lists it in its package.json
// "browser" field as absent, which Bun's bundler does not read. Browsers have
// the same stream classes on globalThis.
const browserStreams: BunPlugin = {
  name: "stream/web from globalThis",
  setup(build) {
    build.onResolve({ filter: /^stream\/web$/u }, () => ({
      path: "stream/web",
      namespace: "browser-streams",
    }));
    build.onLoad({ filter: /.*/u, namespace: "browser-streams" }, () => ({
      contents: "module.exports = globalThis;",
      loader: "js",
    }));
  },
};

export default browserStreams;
