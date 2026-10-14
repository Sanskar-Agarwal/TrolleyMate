import { useTheme } from "../lib/theme";

/** Sun/moon switch. Starts from the OS setting; remembers the shopper's choice. */
export default function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, toggle] = useTheme();
  const toLight = theme === "dark";
  return (
    <button
      type="button"
      className={`theme-toggle ${className}`}
      onClick={toggle}
      aria-label={toLight ? "Switch to light mode" : "Switch to dark mode"}
      title={toLight ? "Light mode" : "Dark mode"}
    >
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        {toLight ? (
          <>
            <circle cx="12" cy="12" r="4.2" />
            <path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" />
          </>
        ) : (
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
        )}
      </svg>
    </button>
  );
}
