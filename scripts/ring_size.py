"""Ring sizes as inside diameters in mm.

Accepted forms: "US 9", "US 9.5", "UK R", "UK R1/2", "EU 59" (ISO 8653: the
inside circumference in mm), "19 mm" or a bare number (inside diameter in mm).

The scales are the ones jewellers' charts use, not quoted from the standards:
- US: 11.63 mm at size 0, plus 0.032 in (0.8128 mm) per size.
- UK: 37.8 mm circumference at A, plus 1.25 mm per letter.
Check a real size against a sizer before casting.
"""

import math
import re

US_ZERO_MM = 11.63
US_STEP_MM = 0.8128
UK_A_CIRC_MM = 37.8
UK_STEP_MM = 1.25
UK_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def inside_diameter(text: str) -> float:
    s = text.strip().upper().replace("½", "1/2")
    if m := re.fullmatch(r"US\s*(\d+(?:\.\d+)?)", s):
        return US_ZERO_MM + US_STEP_MM * float(m[1])
    if m := re.fullmatch(r"UK\s*([A-Z])\s*(1/2)?", s):
        n = UK_LETTERS.index(m[1]) + (0.5 if m[2] else 0.0)
        return (UK_A_CIRC_MM + UK_STEP_MM * n) / math.pi
    if m := re.fullmatch(r"(?:EU|ISO)\s*(\d+(?:\.\d+)?)", s):
        return float(m[1]) / math.pi
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:MM)?", s):
        return float(m[1])
    raise ValueError(f"unknown ring size {text!r}; try 'US 9', 'UK R1/2', 'EU 59' or '19 mm'")


def equivalents(d: float) -> dict:
    """The nearest size on each scale for an inside diameter."""
    us = round((d - US_ZERO_MM) / US_STEP_MM * 4) / 4
    uk = round((d * math.pi - UK_A_CIRC_MM) / UK_STEP_MM * 2) / 2
    uk = min(max(uk, 0.0), len(UK_LETTERS) - 1)
    letter = UK_LETTERS[int(uk)] + ("1/2" if uk % 1 else "")
    return {"diameter_mm": round(d, 2), "circumference_mm": round(d * math.pi, 1),
            "US": f"{us:g}", "UK": letter, "EU": f"{d * math.pi:.0f}"}
