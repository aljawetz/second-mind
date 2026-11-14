import { useState } from "react";
import { getThemeChoice, setThemeChoice, type ThemeChoice } from "../../theme";

const CHOICES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Auto" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export default function ThemePicker() {
  const [choice, setChoice] = useState<ThemeChoice>(getThemeChoice);
  return (
    <div className="theme-picker">
      <span id="theme-picker-label">Appearance</span>
      <div className="theme-choices" role="group" aria-labelledby="theme-picker-label">
        {CHOICES.map((c) => (
          <button
            key={c.value}
            type="button"
            aria-pressed={choice === c.value}
            title={c.value === "system" ? "Follow this computer's light or dark setting" : undefined}
            onClick={() => {
              setChoice(c.value);
              setThemeChoice(c.value);
            }}
          >
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}
