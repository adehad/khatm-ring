"""Where the build reads its inputs and writes its outputs.

Inputs are tracked on this branch. Intermediate files go to CACHE, which is
ignored. Published files go to OUT, a worktree of the `main` branch.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

DESIGN = ROOT / "design"
PARAMS = DESIGN / "ring.toml"
LAYOUT = DESIGN / "inscription-layout.json"

REFERENCE = ROOT / "reference"
SEALS = REFERENCE / "seal"
EXTRACTED = REFERENCE / "extracted"
INSCRIPTION = EXTRACTED / "face-inscription.json"

CACHE = ROOT / "cache"
BODY = CACHE / "body.ply"
STL = CACHE / "khatm-ring.stl"
BLEND = CACHE / "khatm-ring.blend"
STATS = CACHE / "stats.json"
RENDERS = CACHE / "renders"

OUT = ROOT / "out"
OUT_MODEL = OUT / "model"
