import type { SizeScales } from "./ring-spec.ts";

// ring_size.py's scales: US by a fixed step in diameter, UK by a fixed step
// in circumference from A, EU as the circumference in mm.

export interface SizeNames {
  readonly us: string;
  readonly uk: string;
  readonly eu: string;
}

const US_PER_QUARTER = 4;
const UK_PER_HALF = 2;

export function usDiameter(scales: SizeScales, us: number): number {
  return scales.usZeroMm + scales.usStepMm * us;
}

/** ring_size.equivalents: the nearest size on each scale. */
export function sizeNames(scales: SizeScales, diameter: number): SizeNames {
  const us = Math.round(((diameter - scales.usZeroMm) / scales.usStepMm) * US_PER_QUARTER) / US_PER_QUARTER;
  const last = scales.ukLetters.length - 1;
  const ukRaw =
    Math.round(((diameter * Math.PI - scales.ukACircMm) / scales.ukStepMm) * UK_PER_HALF) / UK_PER_HALF;
  const uk = Math.min(Math.max(ukRaw, 0), last);
  return {
    us: String(us),
    uk: (scales.ukLetters[Math.floor(uk)] ?? "") + (uk % 1 === 0 ? "" : "1/2"),
    eu: (diameter * Math.PI).toFixed(0),
  };
}
