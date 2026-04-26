import { Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Streams from "@/pages/Streams";
import Schedule from "@/pages/Schedule";
import Recordings from "@/pages/Recordings";
import TimelineEditor from "@/pages/TimelineEditor";
import Library from "@/pages/Library";
import Watchers from "@/pages/Watchers";
import Settings from "@/pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="streams" element={<Streams />} />
        <Route path="schedule" element={<Schedule />} />
        <Route path="recordings" element={<Recordings />} />
        <Route path="timeline/:id" element={<TimelineEditor />} />
        <Route path="library" element={<Library />} />
        <Route path="watchers" element={<Watchers />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
