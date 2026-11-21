# khatm-ring

A silver seal ring (khatm) modelled in Blender for casting. The round face carries the prophetic seal inscription, top to bottom, الله / رسول / محمد. The band is open and adjustable, with ends that overlap under the finger.

![Renders beside the reference photos](model/renders/contact-sheet.jpg)

## Layout

| Path | Contents |
|---|---|
| `reference/` | Photos of the original ring |
| `extracted/` | Ring cut out of each photo, the rectified face, and the redrawn inscription |
| `scripts/` | Extraction, inscription and Blender build scripts |
| `model/` | Blender file, STL, GLB and renders |

## Weight

The model is sized to **5.80 g in sterling silver**, under the Maliki limit for a man's silver ring of two shar'i dirhams.

| Step | Value | Note |
|---|---|---|
| 1 shar'i dirham | 2.975 g | some put it at 3.0 g |
| Limit, 2 dirhams | 5.95 g | |
| Target, `TARGET_G` | 5.80 g | margin for the dirham dispute and for density |
| Sterling 925 density, `DENSITY_G_MM3` | 10.36 g/cm³ | fine silver is about 10.49 |
| Metal volume | 559.8 mm³ | measured on the finished mesh |

`build_to_weight()` in `scripts/build_ring.py` builds the ring, then rescales the band width so the volume hits the target. Everything else stays fixed. Check the weight on the real casting: sprue position, porosity and polishing all move it.

## Casting

- **One section thickness.** Face plate, bezel wall and band are all close to 0.9 to 1.25 mm, and the back of the face is pocketed under each letter so the plate stays 0.9 mm everywhere.
- **No sharp edges.** Letters, rim, bezel foot and band edges are rounded. The arms are filleted into the bezel.
- **Stays adjustable.** The two band ends overlap with a 0.35 mm gap (`OVERLAP_GAP`), so they do not fuse in the mould.
- **Castable detail.** Letter strokes are 1.22 mm wide, letter holes 0.95 mm, and no pocket is narrower than 0.5 mm.
- **Watertight.** The exported mesh is a single closed shell with no non-manifold edges.

## Assumed dimensions

The photos have no scale reference. Measure the ring and change the constants at the top of `scripts/build_ring.py`.

| Constant | Value |
|---|---|
| `FACE_D` | 17 mm |
| `INNER_D` | 19 mm |
| `BAND_T` | 1.25 mm |
| `BEZEL_H` | 2.7 mm |
| `RELIEF` | 0.6 mm letter height |

Changing `FACE_D` means rerunning `scripts/inscription.py`, which records the face size it was drawn for.

## Rebuild

1. `uv run scripts/extract.py` cuts the ring out of each photo.
2. `uv run scripts/rectify_face.py` warps the tilted face back to a circle.
3. `uv run scripts/inscription.py` draws the inscription as even-width strokes. It writes the letter and back-pocket outlines, and an overlay on the photo for checking.
4. Build the model, either way:
   - Headless: `blender -b --factory-startup -P scripts/build_ring.py -- --render`
   - Live, in an open Blender with the [BlenderMCP](https://github.com/ahujasid/blender-mcp) add-on running: `python scripts/blender_live.py scripts/live_build.py`. The ring rebuilds in the open window. `blender_live.py -c "<python>"` runs any snippet the same way.

Tested with Blender 4.5 LTS.
