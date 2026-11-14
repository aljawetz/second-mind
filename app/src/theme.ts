// The app's appearance: follow the computer, or stay light or dark.
// The choice is kept on this computer; styles.css switches its colour tokens
// on <html data-theme>.
export type ThemeChoice = "system" | "light" | "dark";

const KEY = "sm-theme";
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

export function getThemeChoice(): ThemeChoice {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // No storage: follow the computer.
  }
  return "system";
}

function apply(choice: ThemeChoice) {
  const dark = choice === "dark" || (choice === "system" && systemDark.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function setThemeChoice(choice: ThemeChoice) {
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // The choice still applies until the app closes.
  }
  apply(choice);
}

// Called once, before the first render, so the app never flashes the wrong look.
export function initTheme() {
  apply(getThemeChoice());
  systemDark.addEventListener("change", () => apply(getThemeChoice()));
}
