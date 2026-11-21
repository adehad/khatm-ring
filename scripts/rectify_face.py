# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["opencv-python-headless", "numpy"]
# ///
"""Warp the ring face in the face photo back to a circle.

The photo is taken at a slight tilt, so the face's outline is an ellipse. The
output square is inscribed in the bezel's outer edge; `inscription.py` traces
on top of it.
"""

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SIZE = 800


def main() -> None:
    rgba = cv2.imread(str(ROOT / "extracted" / "02-face-inscription.png"), cv2.IMREAD_UNCHANGED)
    a = (rgba[..., 3] > 128).astype(np.uint8)
    a = cv2.morphologyEx(a, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
    filled = np.zeros_like(a)
    cv2.drawContours(filled, cv2.findContours(a, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], -1, 1, -1)
    # The shank pokes out at the side; a large opening keeps only the round face.
    filled = cv2.morphologyEx(filled, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (81, 81)))
    outline = max(cv2.findContours(filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    (cx, cy), (w, h), ang = cv2.fitEllipse(outline)

    t = np.deg2rad(ang)
    rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    m = rot @ np.diag([SIZE / w, SIZE / h]) @ rot.T
    affine = np.hstack([m, (np.array([SIZE, SIZE]) / 2 - m @ np.array([cx, cy]))[:, None]])
    face = cv2.warpAffine(rgba[..., :3], affine, (SIZE, SIZE), flags=cv2.INTER_CUBIC)
    cv2.imwrite(str(ROOT / "extracted" / "face-crop.png"), face)


if __name__ == "__main__":
    main()
