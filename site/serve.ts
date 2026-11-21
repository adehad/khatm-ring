import index from "./index.html";
import { MODEL } from "./paths.ts";

const server = Bun.serve({
  port: Number(process.env["PORT"] ?? 3000),
  development: true,
  routes: {
    "/": index,
    "/khatm-ring.stl.xz": () => new Response(Bun.file(MODEL)),
  },
});
console.log(`Viewer at ${server.url.href}`);
