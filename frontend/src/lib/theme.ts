import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "trolleymate.theme";

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function storedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

/** The theme in effect: the shopper's saved choice, else the OS setting.
 *  index.html applies the saved choice before first paint, so there's no flash. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Follow OS changes until the shopper picks a theme themselves.
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = () => !storedTheme() && setTheme(systemTheme());
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next: Theme = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* private mode — the choice just won't persist */
      }
      return next;
    });
  }, []);

  return [theme, toggle];
}
