import { NavLink, Outlet } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { authApi } from "@/lib/api";
import { useSession } from "@/lib/query";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/sources", label: "Sources" },
  { to: "/schedule", label: "Schedule" },
  { to: "/recordings", label: "Recordings" },
  { to: "/library", label: "Library" },
  { to: "/watchers", label: "Watchers" },
];

export default function Layout() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: session } = useSession();
  const showLogout = session?.password_set ?? false;

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
        {showLogout && (
          <button
            onClick={async () => {
              await authApi.logout();
              qc.invalidateQueries({ queryKey: ["auth", "me"] });
              nav("/login", { replace: true });
            }}
            className="ml-3 text-xs text-ink-dim hover:text-ink"
          >
            Log out
          </button>
        )}
      </header>
      <main className="flex-1 p-4">
        <Outlet />
      </main>
    </div>
  );
}
