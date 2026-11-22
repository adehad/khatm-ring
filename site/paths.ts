import { join } from "node:path";

// The page fetches the model files by name from beside index.html; the dev
// server and the build both take them from the repo's model folder.
export const MODEL_DIR = join(import.meta.dir, "..", "model");
// The published STL, then the distance field's constants and face rasters.
export const MODEL_FILES = ["khatm-ring.stl.xz", "ring-sdf.json", "face-fields.f16.xz"] as const;
export const DIST = join(import.meta.dir, "dist");
