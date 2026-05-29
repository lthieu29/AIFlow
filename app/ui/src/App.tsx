import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { useEffect } from "react";
import { useAppStore } from "./store";
import { getHealth } from "./api/client";
import NewProject from "./pages/NewProject";
import Timeline from "./pages/Timeline";
import Export from "./pages/Export";
import VoiceGallery from "./pages/VoiceGallery";

// ─── Static page components ───────────────────────────────────────────────────

function HomePage() {
  return (
    <div className="p-8 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold mb-2">AIFlow</h1>
      <p className="text-gray-600 mb-6">
        Personal AI video generation tool. Create a new project or manage
        existing ones.
      </p>
      <nav className="flex flex-wrap gap-3">
        <Link
          to="/new-project"
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          + New Project
        </Link>
        <Link
          to="/voices"
          className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-50 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2"
        >
          Voice Gallery
        </Link>
      </nav>
    </div>
  );
}


function NotFoundPage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-2">404 — Not Found</h1>
      <Link to="/" className="text-blue-600 hover:underline">
        Go home
      </Link>
    </div>
  );
}

// ─── Status bar ───────────────────────────────────────────────────────────────

function StatusBar() {
  const isConnected = useAppStore((s) => s.isConnected);
  const setConnected = useAppStore((s) => s.setConnected);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const health = await getHealth();
        if (!cancelled) {
          setConnected(health.extension_connected);
        }
      } catch {
        if (!cancelled) setConnected(false);
      }
    }

    poll();
    const id = setInterval(poll, 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setConnected]);

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-gray-900 text-white text-xs px-4 py-1 flex items-center gap-2">
      <span
        className={`inline-block w-2 h-2 rounded-full ${
          isConnected ? "bg-green-400" : "bg-red-400"
        }`}
      />
      <span>
        Extension: {isConnected ? "connected" : "disconnected"}
      </span>
    </div>
  );
}

// ─── Root app ─────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50 pb-6">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/new-project" element={<NewProject />} />
          <Route path="/timeline/:projectId" element={<Timeline />} />
          <Route path="/export/:projectId" element={<Export />} />
          <Route path="/voices" element={<VoiceGallery />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </div>
      <StatusBar />
    </BrowserRouter>
  );
}
