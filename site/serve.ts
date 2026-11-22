import index from "./index.html";
import { join } from "node:path";
import { MODEL_DIR, MODEL_FILES } from "./paths.ts";

const server = Bun.serve({
  port: Number(process.env["PORT"] ?? 3000),
  development: true,
  routes: {
    "/": index,
    ...Object.fromEntries(
      MODEL_FILES.map((name) => [`/${name}`, () => new Response(Bun.file(join(MODEL_DIR, name)))]),
    ),
  },
});
console.log(`Viewer at ${server.url.href}`);
