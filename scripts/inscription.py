# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["opencv-python-headless", "numpy"]
# ///
"""Hand-traced outlines of the ring face, written out as SVG and as an overlay.

Coordinates are on a 1000 x 1000 square inscribed in the bezel's outer edge,
in the rectified photo `extracted/face-crop.png` (y down). Each outline is a
closed loop of control points, smoothed with a Catmull-Rom spline. The photo
is too coarse to segment automatically: the shaded side of each letter is as
dark as the oxidised field.
"""

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1000

# Inner edge of the raised rim, i.e. the boundary of the recessed field.
FIELD = [
    (300, 95), (400, 55), (520, 42), (640, 55), (730, 88), (805, 150), (870, 230),
    (912, 330), (930, 450), (922, 560), (900, 655), (852, 760), (782, 852),
    (700, 902), (600, 926), (480, 930), (380, 912), (310, 882), (250, 832),
    (205, 772), (160, 722), (105, 682), (88, 600), (70, 500), (75, 400),
    (100, 322), (150, 250), (210, 170), (250, 128),
]

# Raised letters: (outline, [holes]).
LETTERS = {
    "allah": (
        [
            (250, 292), (240, 232), (255, 180), (290, 140), (330, 112), (365, 104),
            (382, 130), (380, 172), (398, 172), (400, 62), (425, 50), (455, 60),
            (462, 186), (485, 186), (495, 56), (530, 44), (566, 55), (575, 200),
            (592, 250), (565, 282), (450, 300), (350, 312), (290, 307),
        ],
        [[(285, 235), (310, 210), (335, 235), (310, 260)]],
    ),
    "allah_alif": (
        [(640, 70), (672, 58), (702, 85), (705, 160), (700, 280), (672, 302), (645, 282), (634, 160)],
        [],
    ),
    "rasul_left": (
        [
            (110, 332), (158, 315), (198, 348), (200, 420), (188, 500), (192, 562),
            (182, 622), (150, 650), (112, 642), (100, 602), (126, 560), (126, 482), (104, 400),
        ],
        [],
    ),
    "rasul": (
        [
            (238, 470), (250, 422), (290, 400), (332, 404), (366, 430), (382, 466),
            (405, 456), (428, 416), (460, 420), (472, 456), (500, 466), (540, 402),
            (580, 400), (602, 432), (624, 440), (662, 400), (720, 394), (746, 420),
            (732, 470), (700, 508), (650, 530), (560, 560), (450, 580), (350, 596),
            (262, 600), (242, 570), (260, 522), (246, 500),
        ],
        [[(278, 465), (302, 442), (326, 465), (302, 488)]],
    ),
    "rasul_right": (
        [(782, 362), (830, 330), (866, 360), (872, 450), (860, 530), (822, 560), (786, 540), (774, 460)],
        [],
    ),
    "muhammad": (
        [
            (265, 720), (300, 700), (350, 700), (390, 716), (420, 740), (455, 722),
            (500, 712), (570, 690), (590, 668), (612, 650), (672, 600), (702, 568),
            (750, 558), (800, 580), (822, 622), (812, 672), (782, 702), (762, 724),
            (762, 762), (786, 800), (780, 832), (700, 836), (600, 822), (560, 832),
            (540, 856), (500, 866), (460, 850), (440, 822), (410, 810), (380, 832),
            (330, 860), (285, 866), (260, 846), (280, 810), (330, 790), (360, 776),
            (330, 756), (290, 752), (265, 740),
        ],
        [
            [(718, 630), (745, 602), (772, 630), (745, 658)],
            [(485, 775), (510, 750), (535, 775), (510, 800)],
        ],
    ),
}


def catmull_rom(points: list[tuple[int, int]], samples: int = 8) -> np.ndarray:
    p = np.asarray(points, dtype=float)
    n = len(p)
    out = []
    for i in range(n):
        p0, p1, p2, p3 = p[i - 1], p[i], p[(i + 1) % n], p[(i + 2) % n]
        for t in np.linspace(0, 1, samples, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(
                0.5
                * (
                    2 * p1
                    + (-p0 + p2) * t
                    + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
                )
            )
    return np.asarray(out)


def loops() -> dict[str, list[np.ndarray]]:
    """Every outline as dense polylines: field first, then each letter with its holes."""
    result = {"field": [catmull_rom(FIELD)]}
    for name, (outline, holes) in LETTERS.items():
        result[name] = [catmull_rom(outline)] + [catmull_rom(h) for h in holes]
    return result


def write_svg(path: Path) -> None:
    body = []
    for name, rings in loops().items():
        d = " ".join("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in r) + " Z" for r in rings)
        body.append(f'<path id="{name}" d="{d}" fill-rule="evenodd"/>')
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" '
        f'viewBox="0 0 {SIZE} {SIZE}">\n' + "\n".join(body) + "\n</svg>\n"
    )


def write_overlay(path: Path) -> None:
    # Imported here so Blender, which lacks OpenCV, can still import loops().
    import cv2

    img =cv2.resize(cv2.imread(str(ROOT / "extracted" / "face-crop.png")), (SIZE, SIZE))
    paint = img.copy()
    for name, rings in loops().items():
        pts = [r.astype(np.int32) for r in rings]
        if name == "field":
            cv2.polylines(paint, pts, True, (255, 0, 255), 3)
        else:
            cv2.fillPoly(paint, pts, (0, 200, 255))
    cv2.imwrite(str(path), cv2.addWeighted(img, 0.45, paint, 0.55, 0))


def main() -> None:
    out = ROOT / "extracted"
    write_svg(out / "face-inscription.svg")
    write_overlay(out / "face-overlay.png")


if __name__ == "__main__":
    main()
