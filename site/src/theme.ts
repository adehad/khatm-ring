// The <meta name="color-scheme"> tag holds the override ("light" or "dark"),
// or "light dark" to follow the system. The inline script in index.html
// applies the stored value before first paint.
export type Scheme = "light" | "dark";

const STORAGE_KEY = "color-scheme";
const FOLLOW_SYSTEM = "light dark";
const darkQuery = matchMedia("(prefers-color-scheme: dark)");

function meta(): HTMLMetaElement {
  const el = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
  if (el === null) throw new Error('index.html needs <meta name="color-scheme">');
  return el;
}

const systemScheme = (): Scheme => (darkQuery.matches ? "dark" : "light");

export function resolvedScheme(): Scheme {
  const value = meta().content;
  return value === "light" || value === "dark" ? value : systemScheme();
}

// Pressing the button flips what is on screen. Flipping back to the system's
// scheme clears the override, so the page follows the system again.
export function initThemeToggle(button: HTMLButtonElement, onChange: () => void): void {
  button.addEventListener("click", () => {
    const target: Scheme = resolvedScheme() === "dark" ? "light" : "dark";
    const follow = target === systemScheme();
    try {
      if (follow) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, target);
    } catch {
      // Storage blocked: the switch still applies to this page view.
    }
    meta().content = follow ? FOLLOW_SYSTEM : target;
    onChange();
  });
  window.addEventListener("storage", (e) => {
    if (e.key !== STORAGE_KEY) return;
    meta().content = e.newValue ?? FOLLOW_SYSTEM;
    onChange();
  });
  darkQuery.addEventListener("change", onChange);
}
