/**
 * Timeline page — scene editor for a project.
 *
 * Shows the list of scenes with editable fields (prompt, duration, narration),
 * up/down reordering, add/remove, and a "Generate Video" button.
 * Live updates via SSE /api/events.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { apiClient } from "../api/client";

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
  short_id: string;
  title: string;
  status: string;
  skill: string;
  scenes: SceneData[];
}

type GenerationStatus = "idle" | "running" | "success" | "failed";

// ─── Scene row component ──────────────────────────────────────────────────────

interface SceneRowProps {
  scene: SceneData;
  index: number;
  total: number;
  disabled: boolean;
  onChange: (id: string, field: keyof SceneData, value: string | number) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onRemove: (id: string) => void;
}

function SceneRow({
  scene,
  index,
  total,
  disabled,
  onChange,
  onMoveUp,
  onMoveDown,
  onRemove,
}: SceneRowProps) {
  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
          Cảnh {index + 1}
        </span>

        {/* Status badge */}
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            scene.status === "approved"
              ? "bg-green-100 text-green-700"
              : scene.status === "generating"
              ? "bg-yellow-100 text-yellow-700"
              : scene.status === "rejected"
              ? "bg-red-100 text-red-700"
              : "bg-gray-100 text-gray-500"
          }`}
        >
          {scene.status}
        </span>

        {/* Reorder + remove controls */}
        <div className="flex items-center gap-1 ml-auto">
          <button
            type="button"
            onClick={() => onMoveUp(scene.scene_id)}
            disabled={disabled || index === 0}
            aria-label={`Di chuyển cảnh ${index + 1} lên`}
            className="p-1 rounded text-gray-400 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            ▲
          </button>
          <button
            type="button"
            onClick={() => onMoveDown(scene.scene_id)}
            disabled={disabled || index === total - 1}
            aria-label={`Di chuyển cảnh ${index + 1} xuống`}
            className="p-1 rounded text-gray-400 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            ▼
          </button>
          <button
            type="button"
            onClick={() => onRemove(scene.scene_id)}
            disabled={disabled || total <= 1}
            aria-label={`Xóa cảnh ${index + 1}`}
            className="p-1 rounded text-red-300 hover:text-red-600 disabled:opacity-30 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-red-400 ml-1"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Visual prompt */}
      <div>
        <label
          htmlFor={`prompt-${scene.scene_id}`}
          className="block text-xs font-medium text-gray-600 mb-1"
        >
          Prompt hình ảnh
        </label>
        <textarea
          id={`prompt-${scene.scene_id}`}
          value={scene.visual_prompt}
          onChange={(e) => onChange(scene.scene_id, "visual_prompt", e.target.value)}
          disabled={disabled}
          rows={2}
          className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-y disabled:bg-gray-50 disabled:text-gray-400"
        />
      </div>

      {/* Narration */}
      <div>
        <label
          htmlFor={`narration-${scene.scene_id}`}
          className="block text-xs font-medium text-gray-600 mb-1"
        >
          Lời thuyết minh (TTS)
        </label>
        <textarea
          id={`narration-${scene.scene_id}`}
          value={scene.narration}
          onChange={(e) => onChange(scene.scene_id, "narration", e.target.value)}
          disabled={disabled}
          rows={2}
          className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-y disabled:bg-gray-50 disabled:text-gray-400"
        />
      </div>

      {/* Duration */}
      <div className="flex items-center gap-3">
        <label
          htmlFor={`duration-${scene.scene_id}`}
          className="text-xs font-medium text-gray-600 whitespace-nowrap"
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
          className="w-24 border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-gray-50 disabled:text-gray-400"
        />
        <span className="text-xs text-gray-400">3 – 30 s</span>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function Timeline() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [scenes, setScenes] = useState<SceneData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [genStatus, setGenStatus] = useState<GenerationStatus>("idle");
  const [genProgress, setGenProgress] = useState(0);

  const sseRef = useRef<EventSource | null>(null);

  // ─── Load project ──────────────────────────────────────────────────────────

  const loadProject = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get<ProjectDetail>(`/projects/${projectId}`);
      setProject(data);
      // Sort scenes by order
      const sorted = [...(data.scenes ?? [])].sort((a, b) => a.order - b.order);
      setScenes(sorted);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không tải được dự án.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadProject();
  }, [loadProject]);

  // ─── SSE live updates ──────────────────────────────────────────────────────

  useEffect(() => {
    if (!projectId) return;

    const es = new EventSource(
      `/api/events?topics=jobs,scenes,project&project_id=${projectId}`
    );
    sseRef.current = es;

    es.addEventListener("job.update", (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data as string) as {
          status: string;
          progress: number;
        };
        if (payload.status === "running") {
          setGenStatus("running");
          setGenProgress(payload.progress ?? 0);
        } else if (payload.status === "success") {
          setGenStatus("success");
          setGenProgress(1);
        } else if (payload.status === "failed") {
          setGenStatus("failed");
        }
      } catch {
        // ignore parse errors
      }
    });

    es.addEventListener("scene.update", (e: MessageEvent) => {
      try {
        const updated = JSON.parse(e.data as string) as SceneData;
        setScenes((prev) =>
          prev.map((s) => (s.scene_id === updated.scene_id ? { ...s, ...updated } : s))
        );
      } catch {
        // ignore
      }
    });

    es.addEventListener("project.status", (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data as string) as { status: string };
        if (payload.status === "done") {
          setGenStatus("success");
          setGenProgress(1);
        }
      } catch {
        // ignore
      }
    });

    return () => {
      es.close();
      sseRef.current = null;
    };
  }, [projectId]);

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
      prev
        .filter((s) => s.scene_id !== id)
        .map((s, i) => ({ ...s, order: i }))
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
    if (!projectId) return;
    setSaving(true);
    setSaveError(null);
    try {
      // PATCH each scene that has a real ID (not local_*)
      const patches = scenes
        .filter((s) => !s.scene_id.startsWith("local_"))
        .map((s) =>
          apiClient.patch(`/scenes/${s.scene_id}`, {
            order: s.order,
            duration_sec: s.duration_sec,
            narration: s.narration,
            visual_prompt: s.visual_prompt,
          })
        );
      await Promise.all(patches);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Không lưu được các cảnh.");
    } finally {
      setSaving(false);
    }
  }

  // ─── Generate video ────────────────────────────────────────────────────────

  async function handleGenerate() {
    if (!projectId) return;
    setGenStatus("running");
    setGenProgress(0);
    setSaveError(null);
    try {
      // Save first
      await handleSave();
      // Then kick off generation
      await apiClient.post(`/projects/${projectId}/generate`);
    } catch (err: unknown) {
      setGenStatus("failed");
      setSaveError(
        err instanceof Error ? err.message : "Không khởi động được quá trình tạo video."
      );
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────────

  const isGenerating = genStatus === "running";
  const totalDuration = scenes.reduce((sum, s) => sum + s.duration_sec, 0);

  if (loading) {
    return (
      <div className="p-8 text-gray-500" aria-live="polite">
        Đang tải dự án…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <p role="alert" className="text-red-600 mb-4">
          {error}
        </p>
        <Link to="/" className="text-blue-600 hover:underline text-sm">
          ← Về trang chủ
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <Link to="/" className="text-sm text-blue-600 hover:underline">
            ← Quay lại
          </Link>
          <h1 className="text-2xl font-bold mt-1">{project?.title ?? projectId}</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {scenes.length} cảnh ·{" "}
            {totalDuration.toFixed(1)} giây tổng
          </p>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || isGenerating}
            className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            {saving ? "Đang lưu…" : "Lưu"}
          </button>
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={isGenerating || scenes.length === 0}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            {isGenerating ? "Đang tạo…" : "Tạo video"}
          </button>
        </div>
      </div>

      {/* Progress bar */}
      {(isGenerating || genStatus === "success") && (
        <div className="mb-6" aria-live="polite" aria-label="Tiến trình tạo video">
          <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
            <span>
              {genStatus === "success" ? "Tạo video hoàn tất!" : "Đang tạo video…"}
            </span>
            <span>{Math.round(genProgress * 100)}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all duration-500 ${
                genStatus === "success" ? "bg-green-500" : "bg-blue-500"
              }`}
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
                className="text-sm text-blue-600 hover:underline"
              >
                Tới trang Xuất →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Generation failed */}
      {genStatus === "failed" && (
        <div role="alert" className="mb-4 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
          Tạo video thất bại. Kiểm tra log server và thử lại.
        </div>
      )}

      {/* Save error */}
      {saveError && (
        <div role="alert" className="mb-4 rounded border border-orange-300 bg-orange-50 px-4 py-3 text-sm text-orange-700">
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
        className="mt-4 w-full border-2 border-dashed border-gray-300 rounded-lg py-3 text-sm text-gray-400 hover:border-blue-400 hover:text-blue-500 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-400 transition-colors"
      >
        + Thêm cảnh
      </button>

      {/* Bottom export link */}
      {project?.status === "done" && (
        <div className="mt-6 text-center">
          <Link
            to={`/export/${projectId ?? ""}`}
            className="inline-block px-6 py-2 bg-green-600 text-white rounded text-sm font-medium hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
          >
            Xem trang Xuất →
          </Link>
        </div>
      )}
    </div>
  );
}
