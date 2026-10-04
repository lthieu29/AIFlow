/**
 * Timeline page — scene editor for a project.
 *
 * Shows the list of scenes with editable fields (prompt, duration, narration),
 * up/down reordering, add/remove, and a "Generate Video" button.
 * Live updates via SSE /api/events.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import {
  CaretUp,
  CaretDown,
  X,
  Plus,
  ArrowLeft,
  ArrowRight,
  WarningCircle,
  CheckCircle,
  Sparkle,
  SpeakerHigh,
  Stop,
  Image as ImageIcon,
  Trash,
  Upload,
} from "@phosphor-icons/react";
import { apiClient, synthesize, uploadAsset, getAssets, deleteAsset, getAssetImageUrl, getPendingGates } from "../api/client";
import type { AssetInfo, QualityGateInfo } from "../api/client";
import AssetApprovalModal from "../components/AssetApprovalModal";
import { btnPrimary, btnGhost, input as inputCls, card } from "../components/ui";

// ─── Types ────────────────────────────────────────────────────────────────────

interface SceneData {
  scene_id: string;
  order: number;
  duration_sec: number;
  narration: string;
  visual_prompt: string;
  status: string;
  location_hint: string;
}

interface ProjectDetail {
  id: number;
  short_id: string;
  title: string;
  status: string;
  skill: string;
  voice_id: string;
  scenes: SceneData[];
}

type GenerationStatus = "idle" | "running" | "success" | "failed";

/** Per-scene live status emitted by the orchestrator EventBus → SSE bridge. */
type ScenePhase = "pending" | "generating" | "completed" | "failed";

interface SceneProgress {
  status: ScenePhase;
  attempt?: number;
  reason?: string;
}

const STATUS_STYLES: Record<string, string> = {
  approved: "bg-emerald-500/15 text-emerald-300",
  generating: "bg-amber-500/15 text-amber-300",
  rejected: "bg-rose-500/15 text-rose-300",
};

// ─── Scene row ────────────────────────────────────────────────────────────────

interface SceneRowProps {
  scene: SceneData;
  index: number;
  total: number;
  disabled: boolean;
  voice: string;
  progress?: SceneProgress;
  onChange: (id: string, field: keyof SceneData, value: string | number) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onRemove: (id: string) => void;
}

const iconBtn =
  "rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-white/[0.06] hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60";

const SCENE_PHASE_STYLES: Record<ScenePhase, { label: string; cls: string }> = {
  pending: { label: "Chờ", cls: "bg-white/[0.06] text-zinc-400" },
  generating: { label: "Đang tạo", cls: "bg-amber-500/15 text-amber-300 animate-pulse" },
  completed: { label: "Hoàn tất", cls: "bg-emerald-500/15 text-emerald-300" },
  failed: { label: "Thất bại", cls: "bg-rose-500/15 text-rose-300" },
};

function SceneRow({
  scene,
  index,
  total,
  disabled,
  voice,
  progress,
  onChange,
  onMoveUp,
  onMoveDown,
  onRemove,
}: SceneRowProps) {
  return (
    <div className={`${card} space-y-3 p-4`}>
      {/* Header row */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Cảnh {index + 1}
        </span>

        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            STATUS_STYLES[scene.status] ?? "bg-white/[0.06] text-zinc-400"
          }`}
        >
          {scene.status}
        </span>

        {progress && (
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${SCENE_PHASE_STYLES[progress.status].cls}`}
            title={progress.reason ?? undefined}
          >
            {SCENE_PHASE_STYLES[progress.status].label}
            {progress.attempt && progress.attempt > 1 ? ` · lần ${progress.attempt}` : ""}
          </span>
        )}

        <div className="ml-auto flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => onMoveUp(scene.scene_id)}
            disabled={disabled || index === 0}
            aria-label={`Di chuyển cảnh ${index + 1} lên`}
            className={iconBtn}
          >
            <CaretUp size={16} weight="bold" />
          </button>
          <button
            type="button"
            onClick={() => onMoveDown(scene.scene_id)}
            disabled={disabled || index === total - 1}
            aria-label={`Di chuyển cảnh ${index + 1} xuống`}
            className={iconBtn}
          >
            <CaretDown size={16} weight="bold" />
          </button>
          <button
            type="button"
            onClick={() => onRemove(scene.scene_id)}
            disabled={disabled || total <= 1}
            aria-label={`Xóa cảnh ${index + 1}`}
            className={`${iconBtn} hover:bg-rose-500/10 hover:text-rose-400`}
          >
            <X size={16} weight="bold" />
          </button>
        </div>
      </div>

      {/* Visual prompt */}
      <div className="space-y-1.5">
        <label
          htmlFor={`prompt-${scene.scene_id}`}
          className="block text-xs font-medium text-zinc-400"
        >
          Prompt hình ảnh
        </label>
        <textarea
          id={`prompt-${scene.scene_id}`}
          value={scene.visual_prompt}
          onChange={(e) => onChange(scene.scene_id, "visual_prompt", e.target.value)}
          disabled={disabled}
          rows={2}
          className={`${inputCls} resize-y`}
        />
      </div>

      {/* Narration */}
      <div className="space-y-1.5">
        <label
          htmlFor={`narration-${scene.scene_id}`}
          className="block text-xs font-medium text-zinc-400"
        >
          Lời thuyết minh (TTS)
        </label>
        <textarea
          id={`narration-${scene.scene_id}`}
          value={scene.narration}
          onChange={(e) => onChange(scene.scene_id, "narration", e.target.value)}
          disabled={disabled}
          rows={2}
          className={`${inputCls} resize-y`}
        />
        {/* TTS Preview */}
        {scene.narration.trim() && (
          <TTSPreview text={scene.narration} voice={voice} disabled={disabled} />
        )}
      </div>

      {/* Duration */}
      <div className="flex items-center gap-3">
        <label
          htmlFor={`duration-${scene.scene_id}`}
          className="whitespace-nowrap text-xs font-medium text-zinc-400"
        >
          Thời lượng (giây)
        </label>
        <input
          id={`duration-${scene.scene_id}`}
          type="number"
          min={3}
          max={30}
          step={0.5}
          value={scene.duration_sec}
          onChange={(e) =>
            onChange(scene.scene_id, "duration_sec", parseFloat(e.target.value) || 8)
          }
          disabled={disabled}
          className={`${inputCls} w-24`}
        />
        <span className="text-xs text-zinc-500">3 – 30 s</span>
      </div>
    </div>
  );
}

// ─── TTS Preview ──────────────────────────────────────────────────────────────

function TTSPreview({ text, voice, disabled }: { text: string; voice: string; disabled: boolean }) {
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [previewError, setPreviewError] = useState("");

  async function handlePreview() {
    if (playing && audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setPlaying(false);
      return;
    }

    setLoading(true);
    setPreviewError("");
    try {
      const result = await synthesize(text, voice, 1.0);
      // audio_path from server may be absolute or relative to storage dir
      const audioUrl = `/api/tts/audio/${encodeURIComponent(result.audio_path)}`;
      const audio = new Audio(audioUrl);
      audioRef.current = audio;
      audio.onended = () => setPlaying(false);
      audio.onerror = () => setPlaying(false);
      await audio.play();
      setPlaying(true);
    } catch (error) {
      setPlaying(false);
      setPreviewError(error instanceof Error ? error.message : "Mở Colab & giọng đọc để tiếp tục.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <span>
    <button
      type="button"
      onClick={() => void handlePreview()}
      disabled={disabled || loading}
      className={`${iconBtn} inline-flex items-center gap-1 text-xs`}
      aria-label={playing ? "Dừng nghe thử" : "Nghe thử TTS"}
      title={playing ? "Dừng" : "Nghe thử giọng đọc"}
    >
      {playing ? <Stop size={14} weight="fill" /> : <SpeakerHigh size={14} />}
      <span className="text-zinc-500">{loading ? "..." : playing ? "Dừng" : "Nghe thử"}</span>
    </button>
    {previewError && <span role="alert" className="ml-2 text-xs text-amber-300">{previewError} <Link to="/connections" className="underline">Mở kết nối</Link></span>}
    </span>
  );
}

// ─── Asset Panel ──────────────────────────────────────────────────────────────

function AssetPanel({ projectId }: { projectId: number }) {
  const [assets, setAssets] = useState<AssetInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [assetError, setAssetError] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadName, setUploadName] = useState("");
  const [uploadType, setUploadType] = useState<"character" | "product" | "location" | "style">("character");

  const fetchAssets = useCallback(async () => {
    setAssetError("");
    try {
      const result = await getAssets(projectId);
      setAssets(result.assets);
    } catch (err: unknown) {
      setAssetError(err instanceof Error ? err.message : "Không tải được ảnh tham chiếu.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void fetchAssets();
  }, [fetchAssets]);

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file || !uploadName.trim()) return;

    setUploading(true);
    try {
      const newAsset = await uploadAsset(file, projectId, uploadName.trim(), uploadType);
      setAssets((prev) => [...prev, newAsset]);
      setUploadName("");
      setShowUpload(false);
      if (fileRef.current) fileRef.current.value = "";
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Upload thất bại");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Xóa ảnh tham chiếu này?")) return;
    try {
      await deleteAsset(id);
      setAssets((prev) => prev.filter((a) => a.id !== id));
    } catch (err: unknown) {
      setAssetError(err instanceof Error ? err.message : "Không xóa được ảnh tham chiếu.");
    }
  }

  const typeLabels: Record<string, string> = {
    character: "Nhân vật",
    product: "Sản phẩm",
    location: "Phong cảnh",
    style: "Phong cách",
  };

  return (
    <div className={`${card} mt-6 p-4`}>
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-300">
          <ImageIcon size={16} className="text-emerald-400" />
          Ảnh tham chiếu (Reference Images)
        </h2>
        <button
          type="button"
          onClick={() => setShowUpload(!showUpload)}
          className={btnGhost}
        >
          <Upload size={14} />
          Tải lên
        </button>
      </div>

      {assetError && <p role="alert" className="mt-3 text-sm text-rose-300">{assetError}</p>}
      {/* Upload form */}
      {showUpload && (
        <div className="mt-3 space-y-2 rounded-xl border border-white/10 bg-white/[0.02] p-3">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Tên (VD: Nhân vật chính)"
              value={uploadName}
              onChange={(e) => setUploadName(e.target.value)}
              className={`${inputCls} flex-1`}
            />
            <select
              value={uploadType}
              onChange={(e) => setUploadType(e.target.value as typeof uploadType)}
              className={`${inputCls} w-32`}
            >
              <option value="character">Nhân vật</option>
              <option value="product">Sản phẩm</option>
              <option value="location">Phong cảnh</option>
              <option value="style">Phong cách</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".jpg,.jpeg,.png,.webp,.bmp"
              className="flex-1 text-xs text-zinc-400 file:mr-2 file:rounded-lg file:border-0 file:bg-emerald-500/10 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-emerald-400 hover:file:bg-emerald-500/20"
            />
            <button
              type="button"
              onClick={() => void handleUpload()}
              disabled={uploading || !uploadName.trim()}
              className={btnPrimary}
            >
              {uploading ? "..." : "Upload"}
            </button>
          </div>
        </div>
      )}

      {/* Asset grid */}
      {loading ? (
        <p className="mt-3 text-xs text-zinc-500">Đang tải...</p>
      ) : assets.length === 0 ? (
        <p className="mt-3 text-xs text-zinc-500">
          Chưa có ảnh tham chiếu. Upload ảnh nhân vật, phong cảnh hoặc sản phẩm để Veo3 giữ nhất quán giữa các cảnh.
        </p>
      ) : (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
          {assets.map((asset) => (
            <div
              key={asset.id}
              className="group relative overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]"
            >
              <img
                src={getAssetImageUrl(asset.id)}
                alt={asset.name}
                className="aspect-square w-full object-cover"
                loading="lazy"
              />
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5">
                <p className="truncate text-xs font-medium text-zinc-100">{asset.name}</p>
                <p className="text-[10px] text-zinc-400">{typeLabels[asset.type] ?? asset.type}</p>
              </div>
              <button
                type="button"
                onClick={() => void handleDelete(asset.id)}
                className="absolute right-1 top-1 rounded-lg bg-black/60 p-1 text-zinc-400 opacity-0 transition-opacity hover:text-rose-400 group-hover:opacity-100"
                aria-label={`Xóa ${asset.name}`}
              >
                <Trash size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function Timeline() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [scenes, setScenes] = useState<SceneData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(location.state?.parseError ?? null);
  const [genStatus, setGenStatus] = useState<GenerationStatus>("idle");
  const [genProgress, setGenProgress] = useState(0);
  const [jobId, setJobId] = useState<number | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [sceneProgress, setSceneProgress] = useState<Record<number, SceneProgress>>({});
  const [pendingGate, setPendingGate] = useState<QualityGateInfo | null>(null);

  const sseRef = useRef<EventSource | null>(null);

  // ─── Load project ──────────────────────────────────────────────────────────

  const loadProject = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get<{
        id: number;
        short_id: string;
        name: string;
        status: string;
        skill: string;
        voice_id: string;
        scenes: Array<{
          id: number;
          order: number;
          duration: number;
          status: string;
          location_hint: string;
          prompt?: string;
          narration?: string;
        }>;
      }>(`/projects/${projectId}`);

      setProject({
        id: data.id,
        short_id: data.short_id,
        title: data.name,
        status: data.status,
        skill: data.skill,
        voice_id: data.voice_id,
        scenes: [],
      });

      const mapped: SceneData[] = (data.scenes ?? []).map((s) => ({
        scene_id: String(s.id),
        order: s.order,
        duration_sec: s.duration,
        narration: s.narration ?? "",
        visual_prompt: s.prompt ?? "",
        status: s.status,
        location_hint: s.location_hint,
      }));
      mapped.sort((a, b) => a.order - b.order);
      setScenes(mapped);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không tải được dự án.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadProject();
  }, [loadProject]);

  // ─── SSE live updates (job progress) ───────────────────────────────────────

  useEffect(() => {
    if (jobId === null) return;

    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    sseRef.current = es;

    es.addEventListener("job.status", (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data as string) as { status: string };
        if (payload.status === "running") {
          setGenStatus("running");
        } else if (payload.status === "success") {
          setGenStatus("success");
          setGenProgress(1);
        } else if (["failed", "needs_attention", "cancelled"].includes(payload.status)) {
          setGenStatus("failed");
        }
      } catch {
        // ignore parse errors
      }
    });

    es.addEventListener("job.scene_progress", (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data as string) as {
          event_type: string;
          scene_order?: number;
          attempt?: number;
          reason?: string;
        };
        const order = payload.scene_order;
        if (typeof order !== "number") return;
        const phase: ScenePhase =
          payload.event_type === "scene_started"
            ? "generating"
            : payload.event_type === "scene_completed"
            ? "completed"
            : payload.event_type === "scene_failed"
            ? "failed"
            : "pending";
        setSceneProgress((prev) => ({
          ...prev,
          [order]: { status: phase, attempt: payload.attempt, reason: payload.reason },
        }));
      } catch {
        // ignore parse errors
      }
    });

    es.addEventListener("job.gate", (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data as string) as {
          gate_id?: string;
          status?: string;
        };
        if (payload.gate_id !== "G2") return;
        if (payload.status === "checking" && projectId) {
          // Resolve the gate row by querying /gates/pending so we have the
          // numeric id needed for approve/override.
          getPendingGates(projectId)
            .then((gates) => {
              const g2 = gates.find((g) => g.gate_id === "G2");
              if (g2) setPendingGate(g2);
            })
            .catch(() => {
              // no-op
            });
        } else if (payload.status && payload.status !== "checking") {
          // Auto-close the modal when the orchestrator (or another tab)
          // already resolved the gate.
          setPendingGate(null);
        }
      } catch {
        // ignore
      }
    });

    es.addEventListener("job.done", (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data as string) as { status: string };
        if (payload.status === "success") {
          setGenStatus("success");
          setGenProgress(1);
          void loadProject();
        } else {
          setGenStatus("failed");
        }
      } catch {
        // ignore
      }
      es.close();
      sseRef.current = null;
    });

    return () => {
      es.close();
      sseRef.current = null;
    };
  }, [jobId, loadProject, projectId]);

  // ─── Scene mutations ───────────────────────────────────────────────────────

  function handleChange(
    id: string,
    field: keyof SceneData,
    value: string | number
  ) {
    setScenes((prev) =>
      prev.map((s) => (s.scene_id === id ? { ...s, [field]: value } : s))
    );
  }

  function handleMoveUp(id: string) {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.scene_id === id);
      if (idx <= 0) return prev;
      const next = [...prev];
      [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
      return next.map((s, i) => ({ ...s, order: i }));
    });
  }

  function handleMoveDown(id: string) {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.scene_id === id);
      if (idx < 0 || idx >= prev.length - 1) return prev;
      const next = [...prev];
      [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
      return next.map((s, i) => ({ ...s, order: i }));
    });
  }

  function handleRemove(id: string) {
    setScenes((prev) =>
      prev.filter((s) => s.scene_id !== id).map((s, i) => ({ ...s, order: i }))
    );
  }

  function handleAddScene() {
    const newScene: SceneData = {
      scene_id: `local_${Date.now()}`,
      order: scenes.length,
      duration_sec: 8,
      narration: "",
      visual_prompt: "",
      status: "draft",
      location_hint: "unspecified",
    };
    setScenes((prev) => [...prev, newScene]);
  }

  // ─── Save scenes ───────────────────────────────────────────────────────────

  async function handleSave() {
    if (!projectId) return false;
    setSaving(true);
    setSaveError(null);
    try {
      await apiClient.put(`/projects/${projectId}/scenes`, {
        scenes: scenes.map((s) => ({
          id: s.scene_id.startsWith("local_") ? null : Number(s.scene_id),
          duration: s.duration_sec,
          narration: s.narration,
          prompt: s.visual_prompt,
          location_hint: s.location_hint,
        })),
      });
      await loadProject();
      return true;
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Không lưu được các cảnh.");
      return false;
    } finally {
      setSaving(false);
    }
  }

  // ─── Generate video ────────────────────────────────────────────────────────

  async function handleGenerate() {
    if (!projectId) return;
    setGenStatus("running");
    setGenProgress(0);
    setSceneProgress({});
    setPendingGate(null);
    setSaveError(null);
    try {
      if (!(await handleSave())) {
        setGenStatus("idle");
        return;
      }
      const { data } = await apiClient.post<{ job_id: number; status: string }>(
        `/projects/${projectId}/generate`,
        { dry_run: dryRun }
      );
      setJobId(data.job_id);
    } catch (err: unknown) {
      setGenStatus("failed");
      setSaveError(
        err instanceof Error ? err.message : "Không khởi động được quá trình tạo video."
      );
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────────

  const isGenerating = genStatus === "running" || project?.status === "generating";
  const totalDuration = scenes.reduce((sum, s) => sum + s.duration_sec, 0);

  if (loading) {
    return (
      <div className="px-6 py-10 text-sm text-zinc-500" aria-live="polite">
        Đang tải dự án…
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <p
          role="alert"
          className="mb-4 flex items-center gap-2 text-sm text-rose-300"
        >
          <WarningCircle size={18} weight="fill" className="text-rose-400" />
          {error}
        </p>
        <Link to="/" className={btnGhost}>
          <ArrowLeft size={16} />
          Về trang chủ
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <div className="mb-5 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4 text-sm text-zinc-300">
        <p>Giọng đọc chạy trên Colab. Các đoạn đã hoàn thành được lưu trên máy để tiếp tục khi mất kết nối.</p>
        <Link className="mt-2 inline-block font-medium text-emerald-300 underline" to={`/connections?project=${project?.id ?? ""}`}>
          Mở Colab & hàng đợi giọng đọc
        </Link>
      </div>
      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300">
            <ArrowLeft size={16} />
            Quay lại
          </Link>
          <h1 className="mt-1 truncate text-2xl font-semibold tracking-tight text-zinc-50">
            {project?.title ?? projectId}
          </h1>
          <p className="mt-0.5 text-xs text-zinc-500">
            {scenes.length} cảnh · {totalDuration.toFixed(1)} giây tổng
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <label className="mr-1 inline-flex cursor-pointer select-none items-center gap-1.5 text-xs text-zinc-400">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              disabled={isGenerating}
              className="h-3.5 w-3.5 rounded border-white/20 bg-transparent accent-emerald-500"
            />
            <span title="Tạo video placeholder cục bộ, không gọi Veo3, không tốn credit">
              Chạy thử
            </span>
          </label>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || isGenerating}
            className={btnGhost}
          >
            {saving ? "Đang lưu…" : "Lưu"}
          </button>
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={isGenerating || scenes.length === 0}
            className={btnPrimary}
          >
            <Sparkle size={16} weight="fill" />
            {isGenerating ? "Đang tạo…" : "Tạo video"}
          </button>
        </div>
      </div>

      {/* Progress bar */}
      {(isGenerating || genStatus === "success") && (
        <div className="mb-6" aria-live="polite" aria-label="Tiến trình tạo video">
          <div className="mb-1.5 flex items-center justify-between text-xs text-zinc-400">
            <span>
              {genStatus === "success" ? "Tạo video hoàn tất" : "Đang tạo video…"}
            </span>
            <span>{Math.round(genProgress * 100)}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all duration-500"
              style={{ width: `${Math.round(genProgress * 100)}%` }}
              role="progressbar"
              aria-valuenow={Math.round(genProgress * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
          {genStatus === "success" && (
            <div className="mt-2 text-right">
              <button
                type="button"
                onClick={() => navigate(`/export/${projectId ?? ""}`)}
                className="inline-flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300"
              >
                Tới trang Xuất
                <ArrowRight size={16} />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Generation failed */}
      {genStatus === "failed" && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
        >
          <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-rose-400" />
          Tạo video thất bại. Kiểm tra log server và thử lại.
        </div>
      )}

      {/* Save error */}
      {saveError && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
        >
          <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-amber-400" />
          {saveError}
        </div>
      )}

      {/* Scene list */}
      <div className="space-y-3" aria-label="Danh sách cảnh">
        {scenes.map((scene, idx) => (
          <SceneRow
            key={scene.scene_id}
            scene={scene}
            index={idx}
            total={scenes.length}
            disabled={isGenerating}
            voice={project?.voice_id ?? "af_heart"}
            progress={sceneProgress[scene.order]}
            onChange={handleChange}
            onMoveUp={handleMoveUp}
            onMoveDown={handleMoveDown}
            onRemove={handleRemove}
          />
        ))}
      </div>

      {/* Add scene */}
      <button
        type="button"
        onClick={handleAddScene}
        disabled={isGenerating}
        className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-white/15 py-3 text-sm text-zinc-500 transition-colors hover:border-emerald-500/40 hover:text-emerald-400 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60"
      >
        <Plus size={16} weight="bold" />
        Thêm cảnh
      </button>

      {/* Asset panel — reference images for character/location/product */}
      {project && <AssetPanel projectId={project.id} />}

      {/* Bottom export link */}
      {project?.status === "done" && (
        <div className="mt-6 text-center">
          <Link to={`/export/${projectId ?? ""}`} className={btnPrimary}>
            <CheckCircle size={16} weight="fill" />
            Xem trang Xuất
          </Link>
        </div>
      )}

      {/* G2 Asset approval modal — opens when SSE reports gate G2 in checking */}
      <AssetApprovalModal
        open={pendingGate !== null}
        projectId={projectId ?? ""}
        projectDbId={project?.id ?? null}
        gate={pendingGate}
        onClose={() => setPendingGate(null)}
        onResolved={() => setPendingGate(null)}
      />
    </div>
  );
}
