import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import ModelBadge from "./ModelBadge";
import ThemeToggle from "./ThemeToggle";
import "./AppShell.css";

const NAV = {
  shopper: [
    { to: "/shop", label: "Shop" },
    { to: "/household", label: "Household" },
  ],
  dietitian: [{ to: "/review", label: "Review queue" }],
  founder: [
    { to: "/admin", label: "Agent audit" },
    { to: "/review", label: "Exception queue" },
  ],
};

export function Logo() {
  return (
    <span className="logo">
      <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
        <rect width="32" height="32" rx="7" fill="var(--produce)" />
        <path d="M7 9h3l2.4 11h10.2L25 12H11.5" fill="none" stroke="var(--tag)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="13.5" cy="24.5" r="1.8" fill="var(--tag)" />
        <circle cx="21.5" cy="24.5" r="1.8" fill="var(--tag)" />
      </svg>
      <span className="logo-word">Trolley Mate</span>
    </span>
  );
}

export default function AppShell() {
  const { user, signOut } = useAuth();
  if (!user) return null;
  return (
    <div className="shell">
      <header className="topbar">
        <Logo />
        <nav aria-label="Main">
          {NAV[user.role].map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-right">
          <ModelBadge />
          <ThemeToggle />
          <span className="who small">
            <span className="avatar" aria-hidden="true">
              {user.display_name
                .split(" ")
                .filter((w) => /^[A-Z]/.test(w) && w !== "Dr")
                .map((w) => w[0])
                .slice(0, 2)
                .join("")}
            </span>
            <span className="who-text">
              <strong>{user.display_name}</strong>
              <span className="muted"> · {user.role}</span>
            </span>
          </span>
          <button className="btn btn-ghost btn-sm" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  );
}
