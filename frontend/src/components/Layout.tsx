import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/streams", label: "Streams" },
  { to: "/schedule", label: "Schedule" },
  { to: "/library", label: "Library" },
  { to: "/watchers", label: "Watchers" },
];

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col bg-surface-0">
      <header className="flex items-center gap-4 px-4 py-2.5 bg-surface-1 border-b border-border">
        <span className="font-bold tracking-wide">
          <span className="text-terracotta">◉</span> concertpvr
        </span>
        <nav className="flex gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "px-2.5 py-1 rounded text-xs text-ink-dim hover:text-ink",
                  isActive && "bg-terracotta/10 text-terracotta",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1" />
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            cn("text-xs text-ink-dim hover:text-ink", isActive && "text-terracotta")
          }
        >
          ⚙ Settings
        </NavLink>
      </header>
      <main className="flex-1 p-4">
        <Outlet />
      </main>
    </div>
  );
}
