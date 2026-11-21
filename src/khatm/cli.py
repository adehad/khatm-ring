"""`khatm`: one subcommand per build step. Run `khatm -h` for the list."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from khatm import blender_live, inscription, publish, ring_sdf
from khatm.paths import ROOT
from khatm.ring_size import equivalents, inside_diameter

BLENDER_DIR = Path(__file__).resolve().parent / "blender"


def blender_exe() -> str:
    exe = os.environ.get("BLENDER") or shutil.which("blender")
    if exe is None:
        raise SystemExit("Blender not found: set BLENDER to its executable, or put blender on PATH")
    return exe


def build(render: bool, publish_after: bool) -> None:
    cmd = [blender_exe(), "-b", "--factory-startup", "-P", str(BLENDER_DIR / "build_ring.py"), "--"]
    if render:
        cmd.append("--render")
    subprocess.run(cmd, cwd=ROOT, check=True)
    if publish_after:
        publish.main()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="khatm", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    size = sub.add_parser("size", help="convert a ring size: 'US 9', 'UK R1/2', 'EU 59' or '19 mm'")
    size.add_argument("size")
    sub.add_parser("inscription", help="trace the seal and lay the letters out on the face (takes [variant])")
    sub.add_parser("sdf", help="mesh the ring's distance field to a PLY (see khatm sdf -h)", add_help=False)
    b = sub.add_parser("build", help="run Blender headless: mesh, dress and export the ring, then publish")
    b.add_argument("--render", action="store_true", help="also render the views")
    b.add_argument("--no-publish", action="store_true", help="leave the results in cache/")
    sub.add_parser("publish", help="compress the cached STL and renders into the main worktree at out/")
    sub.add_parser("live", help="run a snippet in a live Blender (see khatm live -h)", add_help=False)
    sub.add_parser("live-build", help="rebuild the ring in a live Blender and add the Khatm sidebar panel")

    a, rest = ap.parse_known_args(argv)
    match a.command:
        case "size":
            print(json.dumps(equivalents(inside_diameter(a.size))))
        case "inscription":
            inscription.main(rest)
        case "sdf":
            ring_sdf.main(rest)
        case "build":
            build(a.render, not a.no_publish)
        case "publish":
            publish.main()
        case "live":
            blender_live.main(rest)
        case "live-build":
            blender_live.main([str(BLENDER_DIR / "live_build.py")])
