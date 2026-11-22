import { rm } from "node:fs/promises";
import { join } from "node:path";
import browserStreams from "./browser-streams.ts";
import { DIST, MODEL_DIR, MODEL_FILES } from "./paths.ts";

// GitHub Pages serves every file with a 10-minute cache. Bun names the JS and
// CSS after their content; the model files get the same treatment here, so a
// new model is fetched as soon as index.html (the only unhashed file) expires,
// and an unchanged one stays cached across deploys.
const HASH_CHARS = 12;

await rm(DIST, { recursive: true, force: true });
const result = await Bun.build({
  entrypoints: [join(import.meta.dir, "index.html")],
  outdir: DIST,
  minify: true,
  plugins: [browserStreams],
});
if (!result.success) {
  for (const log of result.logs) console.error(log);
  process.exit(1);
}

async function publishModelFile(name: string): Promise<readonly [string, string]> {
  const file = Bun.file(join(MODEL_DIR, name));
  const hash = new Bun.CryptoHasher("sha256")
    .update(await file.arrayBuffer())
    .digest("hex")
    .slice(0, HASH_CHARS);
  const dot = name.indexOf(".");
  const hashed = `${name.slice(0, dot)}.${hash}${name.slice(dot)}`;
  await Bun.write(join(DIST, hashed), file);
  return [name, hashed];
}

let html = await Bun.file(join(DIST, "index.html")).text();
for (const [name, hashed] of await Promise.all(MODEL_FILES.map((file) => publishModelFile(file)))) {
  const linked = html.replace(`href="${name}"`, `href="${hashed}"`);
  if (linked === html) throw new Error(`index.html has no href="${name}" to version`);
  html = linked;
  console.log(`${name} -> ${hashed}`);
}
await Bun.write(join(DIST, "index.html"), html);
console.log(`${String(result.outputs.length + MODEL_FILES.length)} files in ${DIST}`);
