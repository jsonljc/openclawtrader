import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import LiveOverview from "./pages/LiveOverview";
import Analytics from "./pages/Analytics";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-950 text-gray-100">
        <nav className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center gap-6">
          <span className="text-lg font-bold text-emerald-400">OpenClaw</span>
          <NavLink
            to="/"
            className={({ isActive }) =>
              isActive ? "text-emerald-400 font-medium" : "text-gray-400 hover:text-gray-200"
            }
          >
            Live
          </NavLink>
          <NavLink
            to="/analytics"
            className={({ isActive }) =>
              isActive ? "text-emerald-400 font-medium" : "text-gray-400 hover:text-gray-200"
            }
          >
            Analytics
          </NavLink>
        </nav>
        <main className="p-4 max-w-7xl mx-auto">
          <Routes>
            <Route path="/" element={<LiveOverview />} />
            <Route path="/analytics" element={<Analytics />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
