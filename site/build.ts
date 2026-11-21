import { rm } from "node:fs/promises";
import { basename, join } from "node:path";
import browserStreams from "./browser-streams.ts";
import { DIST, MODEL } from "./paths.ts";

// GitHub Pages serves every file with a 10-minute cache. Bun names the JS and
// CSS after their content; the model gets the same treatment here, so a new
// model is fetched as soon as index.html (the only unhashed file) expires, and
// an unchanged one stays cached across deploys.
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

const model = Bun.file(MODEL);
const hash = new Bun.CryptoHasher("sha256")
  .update(await model.arrayBuffer())
  .digest("hex")
  .slice(0, HASH_CHARS);
const name = basename(MODEL);
const hashedName = name.replace(/\.stl\.xz$/u, `.${hash}.stl.xz`);
await Bun.write(join(DIST, hashedName), model);

const indexPath = join(DIST, "index.html");
const html = await Bun.file(indexPath).text();
const linked = html.replace(`href="${name}"`, `href="${hashedName}"`);
if (linked === html) throw new Error(`index.html has no href="${name}" to version`);
await Bun.write(indexPath, linked);
console.log(`${result.outputs.length + 1} files in ${DIST}, model at ${hashedName}`);
