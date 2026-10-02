import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { useEffect } from "react";
import { Plus, Waveform, FilmSlate, ArrowLeft, ListBullets } from "@phosphor-icons/react";
import { useAppStore } from "./store";
import { getHealth } from "./api/client";
import { btnPrimary, btnGhost } from "./components/ui";
import NewProject from "./pages/NewProject";
import Timeline from "./pages/Timeline";
import Export from "./pages/Export";
import VoiceGallery from "./pages/VoiceGallery";
import Dashboard from "./pages/Dashboard";
import AudioStudio from "./pages/AudioStudio";
import VoiceTraining from "./pages/VoiceTraining";
import StudioSettings from "./pages/StudioSettings";
import ScriptStudio from "./pages/ScriptStudio";
import ProductionStudio, { WorkspaceNav } from "./pages/ProductionStudio";

// ─── Home ─────────────────────────────────────────────────────────────────────

function HomePage() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-20">
      <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-zinc-400">
        <Waveform size={14} weight="fill" className="text-emerald-400" />
        Công cụ tạo video AI cá nhân
      </span>
      <h1 className="mt-4 flex items-center gap-3 text-4xl font-semibold tracking-tight text-zinc-50">
        <FilmSlate size={36} weight="duotone" className="text-emerald-400" />
        AIFlow
      </h1>
      <p className="mt-3 max-w-md leading-relaxed text-zinc-400">
        Biến ý tưởng, sản phẩm hay kịch bản thành video hoàn chỉnh. Tạo dự án mới
        hoặc quản lý thư viện giọng nói của bạn.
      </p>
      <nav className="mt-8 flex flex-wrap gap-3">
        <Link to="/scripts" className={btnPrimary}>
          <ListBullets size={18} /> Kịch bản & phiên bản
        </Link>
        <Link to="/connections" className={btnPrimary}>
          <Waveform size={18} /> Colab & giọng đọc
        </Link>
        <Link to="/new-project" className={btnPrimary}>
          <Plus size={18} weight="bold" />
          Dự án mới
        </Link>
        <Link to="/projects" className={btnGhost}>
          <ListBullets size={18} />
          Dự án của tôi
        </Link>
        <Link to="/voices" className={btnGhost}>
          <Waveform size={18} />
          Thư viện giọng nói
        </Link>
      </nav>
    </div>
  );
}

function NotFoundPage() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-20">
      <p className="text-sm font-medium text-emerald-400">404</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-50">
        Không tìm thấy trang
      </h1>
      <Link to="/" className={`${btnGhost} mt-6`}>
        <ArrowLeft size={18} />
        Về trang chủ
      </Link>
    </div>
  );
}

// ─── Status bar ─────────────────────────────────────────────────────────────

function StatusBar() {
  const isConnected = useAppStore((s) => s.isConnected);
  const setConnected = useAppStore((s) => s.setConnected);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const health = await getHealth();
        if (!cancelled) setConnected(health.extension_connected);
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
    <div className="fixed bottom-4 right-4 z-30 flex items-center gap-2 rounded-full border border-white/10 bg-zinc-900/80 px-3.5 py-1.5 text-xs text-zinc-300 shadow-lg shadow-black/40 backdrop-blur">
      <span className="relative flex h-2 w-2">
        {isConnected && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/70" />
        )}
        <span
          className={`relative inline-flex h-2 w-2 rounded-full ${
            isConnected ? "bg-emerald-400" : "bg-rose-400"
          }`}
        />
      </span>
      Extension: {isConnected ? "đã kết nối" : "mất kết nối"}
    </div>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-[100dvh] bg-zinc-950 text-zinc-100">
        <WorkspaceNav />
        <Routes>
          <Route path="/production" element={<ProductionStudio />} />
          <Route path="/work-queue" element={<ProductionStudio view="queue" />} />
          <Route path="/library" element={<ProductionStudio view="library" />} />
          <Route path="/welcome" element={<HomePage />} />
          <Route path="/scripts" element={<ScriptStudio />} />
          <Route path="/connections" element={<AudioStudio />} />
          <Route path="/voice-training" element={<VoiceTraining />} />
          <Route path="/studio-settings" element={<StudioSettings />} />
          <Route path="/queue" element={<AudioStudio />} />
          <Route path="/" element={<ProductionStudio view="overview" />} />
          <Route path="/projects" element={<Dashboard />} />
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
