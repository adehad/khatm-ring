import { createElement, Download, Moon, RotateCw, Ruler, Sun, type IconNode } from "lucide";

// Controls name their icon with data-icon; the icon goes before the label.
const ICONS: Readonly<Record<string, IconNode>> = {
  download: Download,
  moon: Moon,
  ruler: Ruler,
  spin: RotateCw,
  sun: Sun,
};

export function placeIcons(root: ParentNode = document): void {
  for (const el of root.querySelectorAll<HTMLElement>("[data-icon]")) {
    const name = el.dataset["icon"];
    const icon = name === undefined ? undefined : ICONS[name];
    if (icon === undefined) throw new Error(`no icon named ${name ?? "(none)"}`);
    const svg = createElement(icon, { "aria-hidden": "true", width: 18, height: 18 });
    el.prepend(svg);
  }
}
