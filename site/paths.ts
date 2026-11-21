import { join } from "node:path";

// The page fetches the model by its file name from beside index.html; the dev
// server and the build both take it from the repo's model folder.
export const MODEL = join(import.meta.dir, "..", "model", "khatm-ring.stl.xz");
export const DIST = join(import.meta.dir, "dist");
