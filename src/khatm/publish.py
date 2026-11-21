"""Copy a finished build from the cache into the `main` worktree at `out/`.

The STL is binary. Its per-facet normals are zeroed: the mesh's winding already
fixes them, slicers and the web viewer recompute them, and zeros compress far
better. Its 80-byte header carries the stats the viewer shows, as `key=value`
pairs, and the commit of this branch it was built from, with a "+" when the
working tree had uncommitted changes. The file is then xz-compressed.
"""

import json
import lzma
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from khatm.paths import EXTRACTED, OUT, OUT_MODEL, RENDERS, ROOT, STATS, STL

STL_HEADER = 80
FACET = np.dtype([("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attr", "<u2")])
RENDER_QUALITY = 90
SHEET_TILE = 450
SHEET_RENDERS = (("face", "three-quarter", "low-three-quarter"), ("front", "side", "underside"))
SHEET_PHOTOS = ("02-face-inscription", "05-band-three-quarter")
PHOTO_BACKGROUND = (236, 230, 220)


def build_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()

    dirty = git("status", "--porcelain", "--untracked-files=no") != ""
    return git("rev-parse", "--short=7", "HEAD") + ("+" if dirty else "")


def header(stats: dict, commit: str) -> bytes:
    size = stats["size"]
    pairs = {
        "build": commit,
        "field_z": f"{stats['z_field']:.4f}",
        "grams": f"{stats['grams_925']:.2f}",
        "inside_d": f"{size['diameter_mm']:.2f}",
        "us": size["US"],
        "uk": size["UK"],
    }
    text = "khatm " + " ".join(f"{k}={v}" for k, v in pairs.items())
    raw = text.encode("ascii")
    if len(raw) > STL_HEADER:
        raise ValueError(f"STL header is {len(raw)} bytes, over {STL_HEADER}: {text}")
    return raw.ljust(STL_HEADER, b" ")


def compact_stl(stl: bytes, stats: dict, commit: str) -> bytes:
    count = int(np.frombuffer(stl, "<u4", 1, STL_HEADER)[0])
    facets = np.frombuffer(stl, FACET, count, STL_HEADER + 4).copy()
    facets["normal"] = 0
    facets["attr"] = 0
    return header(stats, commit) + np.uint32(count).tobytes() + facets.tobytes()


def photo_tile(name: str) -> Image.Image:
    """A reference cut-out, cropped square around the ring, on a plain background."""
    cut = Image.open(EXTRACTED / f"{name}.png").convert("RGBA")
    box = cut.getchannel("A").getbbox()
    if box is None:
        raise ValueError(f"{name}.png is fully transparent")
    left, top, right, bottom = box
    side = int(max(right - left, bottom - top) * 1.25)
    cx, cy = (left + right) // 2, (top + bottom) // 2
    square = Image.new("RGBA", (side, side), (*PHOTO_BACKGROUND, 255))
    square.alpha_composite(cut.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2)))
    return square.convert("RGB").resize((SHEET_TILE, SHEET_TILE), Image.Resampling.LANCZOS)


def contact_sheet(folder: Path) -> Image.Image:
    """Two rows: three renders then a reference photo of the same ring."""
    rows = [
        [Image.open(folder / f"{v}.png").convert("RGB").resize((SHEET_TILE, SHEET_TILE)) for v in views]
        + [photo_tile(photo)]
        for views, photo in zip(SHEET_RENDERS, SHEET_PHOTOS, strict=True)
    ]
    sheet = Image.new("RGB", (SHEET_TILE * len(rows[0]), SHEET_TILE * len(rows)))
    for r, row in enumerate(rows):
        for c, tile in enumerate(row):
            sheet.paste(tile, (c * SHEET_TILE, r * SHEET_TILE))
    return sheet


def main() -> None:
    if not (OUT / ".git").exists():
        raise SystemExit(f"{OUT} is not a worktree of main; run: git worktree add out main")
    stats = json.loads(STATS.read_text(encoding="utf-8"))
    OUT_MODEL.mkdir(parents=True, exist_ok=True)
    packed = lzma.compress(compact_stl(STL.read_bytes(), stats, build_commit()), preset=9 | lzma.PRESET_EXTREME)
    (OUT_MODEL / "khatm-ring.stl.xz").write_bytes(packed)
    print(f"khatm-ring.stl.xz  {len(packed) / 1e6:.2f} MB")

    renders = OUT_MODEL / "renders"
    renders.mkdir(exist_ok=True)
    for png in sorted(RENDERS.glob("*.png")):
        Image.open(png).save(renders / f"{png.stem}.webp", quality=RENDER_QUALITY)
    contact_sheet(RENDERS).save(renders / "contact-sheet.webp", quality=RENDER_QUALITY)
    print(f"renders -> {renders}")


if __name__ == "__main__":
    main()
