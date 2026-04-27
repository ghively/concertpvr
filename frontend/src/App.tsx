import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Sources from "@/pages/Sources";
import Schedule from "@/pages/Schedule";
import Library from "@/pages/Library";
import Watchers from "@/pages/Watchers";
import WatcherDetail from "@/pages/WatcherDetail";
import Settings from "@/pages/Settings";
import Recordings from "@/pages/Recordings";
import TimelineEditor from "@/pages/TimelineEditor";
import Login from "@/pages/Login";
import { useSession } from "@/lib/query";

function AuthGate({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useSession();
  if (isLoading) {
    return <div className="text-ink-dim text-xs p-8">Loading…</div>;
  }
  if (data && data.password_set && !data.authenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<AuthGate><Layout /></AuthGate>}>
        <Route index element={<Dashboard />} />
        <Route path="streams" element={<Navigate to="/sources" replace />} />
        <Route path="sources" element={<Sources />} />
        <Route path="schedule" element={<Schedule />} />
        <Route path="recordings" element={<Recordings />} />
        <Route path="timeline/:id" element={<TimelineEditor />} />
        <Route path="library" element={<Library />} />
        <Route path="watchers" element={<Watchers />} />
        <Route path="watchers/:id" element={<WatcherDetail />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
