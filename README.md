# khatm-ring

A silver seal ring (khatm) modelled in Blender for casting. The round face carries the prophetic seal inscription, top to bottom, الله / رسول / محمد. The band is open: its ends overlap under the finger, and you size the ring by bending them.

![Renders beside the reference photos](model/renders/contact-sheet.jpg)

## Layout

| Path | Contents |
|---|---|
| `reference/` | Photos of the original ring |
| `reference/seal/` | Public-domain renderings of the seal the letters are traced from, with `SOURCES.md` |
| `design/inscription-layout.json` | Hand-tuned position, turn and scale of each letter piece |
| `extracted/` | Ring cut out of each photo, and the laid-out inscription |
| `scripts/` | Extraction, inscription and Blender scripts |
| `model/` | Blender file, STL, GLB and renders |

## Inscription

The letters are traced from a seal rendering in `reference/seal/`, not redrawn, so they keep their thick and thin strokes and tapered ends. `inscription.py` emboldens them to the weight of the original ring and rounds off any tip too fine to cast.

Each connected letter group is a piece: `allah_1`, `allah_2`, `rasul_1` to `rasul_3` and `muhammad_1`, numbered right to left within each line. See `extracted/inscription-labelled.png`.

To rebalance the pieces, either:

- edit `design/inscription-layout.json` (`dx` and `dy` in mm, `rotate` in degrees, `scale`), or
- drag them in Blender. Send `exec(open(r"scripts/live_letters.py").read()); show()` to lay the pieces over the face, move them in top view, then send `read_back()`.

Then run `uv run scripts/inscription.py` and rebuild. It warns when two pieces come within 0.35 mm of each other or of the rim.

Three source renderings are wired in: `canonical`, `impression` (default, the most hand-cut) and `asymmetric`. `uv run scripts/inscription.py asymmetric` switches; `extracted/inscription-variants.jpg` compares them with the original ring.

## Form

`scripts/ring_sdf.py` models the whole ring as one signed distance field and meshes it once with marching cubes. Parts are joined with smooth unions, so every join is a fillet by construction:

- **Head.** There is no ledge under the face. Across the finger, the wall drops from the crown round and leans out a little (`HEAD_FLARE`) until it runs into the band. Along the finger, the underside follows the band's curve and rises to the face edge, so from the side the head is a boat that narrows into the band. The back is open, with a rolled lip and a domed ceiling, and the hollow's wall meets the finger hole along its tangent.
- **Band.** It flares to 8.5 mm wide and 1.3 mm thick under the head, along one eased curve for width and thickness. It then thins to rounded tips 0.9 mm thick, which you bend to size. A faint width wave keeps it from looking machined.
- **Joins.** The shoulders blend into the head with a 1.5 mm fillet (`K_SHOULDER`). The fillet fades to nothing before the overlap, so the two ends never fuse.
- **Face.** The rim's outer edge is a true circle. Its inner edge follows the hand-cut border of the seal reference, and a 45° bevel leads down into the oxidised field.

## Weight

The model is sized to **5.80 g in sterling silver**, under the Maliki limit for a man's silver ring of two shar'i dirhams.

| Step | Value | Note |
|---|---|---|
| 1 shar'i dirham | 2.975 g | some put it at 3.0 g |
| Limit, 2 dirhams | 5.95 g | |
| Target, `TARGET_G` | 5.80 g | margin for the dirham dispute and for density |
| Sterling 925 density, `DENSITY_G_MM3` | 10.36 g/cm³ | fine silver is about 10.49 |

`ring_sdf.py --solve` adjusts only the band's end width until the volume meets the target, so the shoulder flare is kept. It counts metal on a 0.1 mm grid in seconds, then meshes at 0.05 mm. Weigh the real casting: sprue position, porosity and polishing all move it.

## Casting

- Sections stay between about 0.6 mm (centre of the face plate) and 1.3 mm.
- Letter features are at least 0.4 mm wide, counters at least 0.6 mm.
- Every outside edge is rounded; the arms are blended into the head.
- The band ends overlap with a 0.35 mm gap (`OVERLAP_GAP`), so they do not fuse in the mould.
- The exported mesh is one closed shell with no non-manifold edges.

## Rebuild

1. `uv run scripts/extract.py` cuts the ring out of each photo.
2. `uv run scripts/inscription.py [variant]` traces and lays out the inscription.
3. Build the model, either way. Both run `ring_sdf.py --solve` through uv, import the mesh, then add materials and export.
   - Headless: `blender -b --factory-startup -P scripts/build_ring.py -- --render`
   - Live, in an open Blender with the [BlenderMCP](https://github.com/ahujasid/blender-mcp) add-on running (start Blender with `--addons addon`): `python scripts/blender_live.py scripts/live_build.py`. The ring rebuilds in the open window.

Tested with Blender 4.5 LTS. Sizes are estimates from the photos; the constants at the top of `scripts/ring_sdf.py` are the knobs.
