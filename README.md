# khatm-ring

3D reconstruction in Blender of a silver seal ring (khatm). The round face carries raised calligraphy reading, top to bottom, الله / رسول / محمد. The shank is an open, adjustable band whose ends overlap under the finger.

![Renders beside the reference face](model/renders/contact-sheet.jpg)

## Layout

| Path | Contents |
|---|---|
| `reference/` | Source photos of the ring |
| `extracted/` | Ring cut out of each photo, the rectified face, and the traced inscription |
| `scripts/` | Extraction, tracing and Blender build scripts |
| `model/` | Blender file, STL, GLB and renders |

## Rebuild

1. `uv run scripts/extract.py` cuts the ring out of each photo.
2. `uv run scripts/rectify_face.py` rectifies the face to a circle (`extracted/face-crop.png`).
3. `uv run scripts/inscription.py` writes the hand-traced outlines to `extracted/face-inscription.svg` and an overlay on the photo to check the fit.
4. `blender -b --factory-startup -P scripts/build_ring.py -- --render` builds the model, exports it and renders five views. Tested with Blender 4.5 LTS.

The inscription is hand-traced in `scripts/inscription.py`. The photo is too coarse for automatic segmentation: the shaded side of each letter is as dark as the oxidised field.

## Assumed dimensions

The photos have no scale reference, so every size is estimated from finger widths. Measure the ring and change the constants at the top of `scripts/build_ring.py`.

| Constant | Value | Estimated from |
|---|---|---|
| `FACE_D` | 17 mm | face about one fingertip wide |
| `INNER_D` | 19 mm | typical size; the band is adjustable |
| `BAND_T` | 1.3 mm | band edge, photos 1 and 5 |
| `BAND_W_TOP` to `BAND_W_END` | 7 to 4.5 mm | taper in photos 4 and 5 |
| `BEZEL_H` | 3.2 mm | side view, photo 4 |
| `FIELD_DEPTH` | 0.5 mm | letters sit flush with the rim |
