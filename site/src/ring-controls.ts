import { RingGpu } from "./gpu/ring-gpu.ts";
import { linkedUrl, ringFromStl, type LoadedRing } from "./model.ts";
import { rebuildRing, type BuiltRing, type Stage } from "./rebuild.ts";
import { loadRingSpec, type RingSpec } from "./ring-spec.ts";
import { sizeNames, usDiameter } from "./sizes.ts";
import { facetCount, type RingInfo } from "./stl.ts";

// What the page says about the ring on show, its STL download, and the size
// picker, which rebuilds the ring on the GPU or goes back to the published STL.

const REPO_URL = "https://github.com/adehad/khatm-ring";
const PUBLISHED = "published";
const US_SIZES = { first: 4, last: 13, step: 0.5 } as const;
const NO_WEBGPU = "Changing the size needs a browser with WebGPU.";

const STAGE_TEXT: Readonly<Record<Stage, string>> = {
  solving: "sizing the band",
  meshing: "meshing",
  weighing: "weighing",
  simplifying: "simplifying",
};

export interface RingControls {
  readonly published: LoadedRing;
  readonly details: HTMLElement;
  readonly build: HTMLElement;
  readonly download: HTMLButtonElement;
  /** Opens `sizes` and shows the size on show. */
  readonly sizeButton: HTMLButtonElement;
  readonly sizeLabel: HTMLElement;
  /** A popover the size buttons go in. */
  readonly sizes: HTMLElement;
  /** Puts a ring in the scene in place of the last one. */
  readonly show: (ring: LoadedRing) => void;
  readonly status: (text: string) => void;
}

// Links the build commit the model came from. A "+" means it was built with
// uncommitted changes, so no commit matches it exactly.
function buildLine(commit: string, rebuilt: boolean): (string | HTMLAnchorElement)[] {
  const sha = commit.replace(/\+$/u, "");
  const link = document.createElement("a");
  link.href = `${REPO_URL}/commit/${sha}`;
  link.textContent = sha;
  const local = sha === commit ? "" : " with local changes";
  return [rebuilt ? "Rebuilt in your browser from " : "Built from ", link, local];
}

function describe(info: RingInfo, built: BuiltRing | undefined): string {
  const short = built !== undefined && !built.reachedTarget ? " (band ends at their limit)" : "";
  return `${info.grams.toFixed(2)} g${short} · US ${info.us} · UK ${info.uk} · ${info.insideDiameter.toFixed(1)} mm inside`;
}

function sizeLabel(spec: RingSpec, diameter: number): string {
  const names = sizeNames(spec.ringSize, diameter);
  return `US ${names.us} · UK ${names.uk} · ${diameter.toFixed(1)} mm`;
}

function sizeButton(value: string, text: string): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.value = value;
  button.textContent = text;
  button.setAttribute("aria-pressed", String(value === PUBLISHED));
  return button;
}

function sizeButtons(spec: RingSpec, published: RingInfo): HTMLButtonElement[] {
  const buttons = [sizeButton(PUBLISHED, `${sizeLabel(spec, published.insideDiameter)} (as published)`)];
  for (let us = US_SIZES.first; us <= US_SIZES.last; us += US_SIZES.step) {
    const d = usDiameter(spec.ringSize, us);
    buttons.push(sizeButton(d.toFixed(4), sizeLabel(spec, d)));
  }
  return buttons;
}

type Present = (ring: LoadedRing, built?: BuiltRing) => void;

/** Shows a ring: in the scene, in the header, and behind the STL button. */
function presenter(controls: RingControls): Present {
  let url = "";
  let name = "";
  controls.download.addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
  });
  return (ring, built) => {
    controls.show(ring);
    controls.details.textContent = describe(ring.info, built);
    controls.sizeLabel.textContent = `US ${ring.info.us} · ${ring.info.insideDiameter.toFixed(1)} mm`;
    controls.build.replaceChildren(...buildLine(ring.info.build, built !== undefined));
    URL.revokeObjectURL(url);
    url = URL.createObjectURL(new Blob([ring.stl], { type: "model/stl" }));
    name = built === undefined ? "khatm-ring.stl" : `khatm-ring-us-${ring.info.us}.stl`;
    controls.download.disabled = false;
    controls.status("");
  };
}

function listenForSizes(spec: RingSpec, controls: RingControls, present: Present): void {
  const { published, sizes, status } = controls;
  let gpu: Promise<RingGpu> | undefined;
  const rebuild = async (insideD: number): Promise<void> => {
    const name = `US ${sizeNames(spec.ringSize, insideD).us}`;
    gpu ??= RingGpu.create(spec);
    const built = await rebuildRing(await gpu, spec, {
      insideD,
      build: published.info.build,
      targetFacets: facetCount(published.stl),
      onStage: (stage, fraction) => {
        const percent = stage === "meshing" ? ` ${String(Math.round(fraction * 100))}%` : "";
        status(`${name}: ${STAGE_TEXT[stage]}…${percent}`);
      },
    });
    present(ringFromStl(built.stl), built);
  };

  sizes.addEventListener("click", (event) => {
    const chosen = event.target instanceof Element ? event.target.closest("button") : null;
    if (chosen === null) return;
    sizes.hidePopover();
    for (const button of sizes.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button === chosen));
    }
    if (chosen.value === PUBLISHED) {
      present(published);
      return;
    }
    controls.sizeButton.disabled = true;
    rebuild(Number(chosen.value))
      .catch((error: unknown) => {
        status(navigator.gpu === undefined ? NO_WEBGPU : "Could not rebuild the ring.");
        console.error(error);
      })
      .finally(() => {
        controls.sizeButton.disabled = false;
      });
  });
}

export async function initRingControls(controls: RingControls): Promise<void> {
  const present = presenter(controls);
  present(controls.published);
  if (!("gpu" in navigator)) {
    controls.sizeButton.title = NO_WEBGPU;
    return;
  }
  const spec = await loadRingSpec(linkedUrl("ring-sdf"), linkedUrl("face-fields"));
  controls.sizes.replaceChildren(...sizeButtons(spec, controls.published.info));
  controls.sizeButton.disabled = false;
  listenForSizes(spec, controls, present);
}
