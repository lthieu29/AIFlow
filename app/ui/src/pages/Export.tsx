/**
 * Export page — final video preview + download.
 *
 * Shows an HTML5 video player for the rendered final.mp4,
 * download buttons for the video and SRT subtitle,
 * basic export quality options, and a copy-link button.
 */

import { useState, useEffect, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  DownloadSimple,
  FileText,
  LinkSimple,
  Check,
  WarningCircle,
  FilmStrip,
} from "@phosphor-icons/react";
import { apiClient } from "../api/client";
import Combobox, { type ComboOption } from "../components/Combobox";
import { btnPrimary, btnGhost, card, fieldLabel } from "../components/ui";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ProjectSummary {
  short_id: string;
  title: string;
  status: string;
  skill: string;
  created_at: string;
}

type ExportQuality = "original" | "1080p" | "720p" | "480p";
type ExportFormat = "mp4" | "webm";

const QUALITY_OPTIONS: ComboOption[] = [
  { value: "original", label: "Gốc (như khi render)" },
  { value: "1080p", label: "1080p" },
  { value: "720p", label: "720p" },
  { value: "480p", label: "480p" },
];

// ─── Component ────────────────────────────────────────────────────────────────

export default function Export() {
  const { projectId } = useParams<{ projectId: string }>();

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [quality, setQuality] = useState<ExportQuality>("original");
  const [format, setFormat] = useState<ExportFormat>("mp4");
  const [copied, setCopied] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);

  // ─── Load project summary ──────────────────────────────────────────────────

  useEffect(() => {
    if (!projectId) return;

    setLoading(true);
    setError(null);

    apiClient
      .get<ProjectSummary>(`/projects/${projectId}`)
      .then(({ data }) => {
        setProject(data);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Không tải được dự án.");
      })
      .finally(() => setLoading(false));
  }, [projectId]);

  // ─── Derived URLs ──────────────────────────────────────────────────────────

  const videoSrc = projectId ? `/api/projects/${projectId}/output` : "";
  const downloadUrl = projectId
    ? `/api/projects/${projectId}/output?download=1`
    : "";
  const srtUrl = projectId ? `/api/projects/${projectId}/export/srt` : "";
  const shareUrl =
    typeof window !== "undefined"
      ? `${window.location.origin}/export/${projectId ?? ""}`
      : "";

  // ─── Handlers ─────────────────────────────────────────────────────────────

  async function handleCopyLink() {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback: select a hidden input
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────────

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
        <p role="alert" className="mb-4 flex items-center gap-2 text-sm text-rose-300">
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

  const isReady = project?.status === "done";

  const downloadBtn = `${btnPrimary} px-5 py-2.5 ${
    isReady ? "" : "pointer-events-none opacity-40"
  }`;
  const srtBtn = `${btnGhost} px-5 py-2.5 ${
    isReady ? "" : "pointer-events-none opacity-40"
  }`;

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      {/* Header */}
      <Link
        to={`/timeline/${projectId ?? ""}`}
        className="inline-flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300"
      >
        <ArrowLeft size={16} />
        Quay lại timeline
      </Link>
      <h1 className="mt-3 truncate text-2xl font-semibold tracking-tight text-zinc-50">
        {project?.title ?? projectId}
      </h1>
      <p className="mt-0.5 text-xs text-zinc-500">
        Trạng thái:{" "}
        <span className={isReady ? "font-medium text-emerald-400" : "font-medium text-amber-400"}>
          {project?.status ?? "không rõ"}
        </span>
      </p>

      {/* Not ready notice */}
      {!isReady && (
        <div
          role="status"
          className="mt-6 flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
        >
          <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-amber-400" />
          <span>
            Video chưa sẵn sàng. Quay lại{" "}
            <Link to={`/timeline/${projectId ?? ""}`} className="font-medium text-amber-100 underline">
              timeline
            </Link>{" "}
            và bấm "Tạo video".
          </span>
        </div>
      )}

      {/* Video player */}
      <div className="mt-6 aspect-video overflow-hidden rounded-2xl border border-white/10 bg-black shadow-xl shadow-black/40">
        {isReady ? (
          <video
            ref={videoRef}
            src={videoSrc}
            controls
            playsInline
            preload="metadata"
            className="h-full w-full"
            aria-label={`Xem trước ${project?.title ?? "dự án"}`}
          >
            <track kind="captions" src={srtUrl} label="Tiếng Việt" default />
            Trình duyệt của bạn không hỗ trợ thẻ video.
          </video>
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-sm text-zinc-600">
            <FilmStrip size={32} weight="duotone" />
            Video chưa có sẵn
          </div>
        )}
      </div>

      {/* Export options */}
      <div className={`${card} mt-6 space-y-4 p-5`}>
        <h2 className="text-sm font-semibold text-zinc-200">Tùy chọn xuất</h2>

        {/* Quality */}
        <div className="max-w-xs space-y-1.5">
          <label htmlFor="quality" className={fieldLabel}>
            Chất lượng
          </label>
          <Combobox
            id="quality"
            value={quality}
            onChange={(v) => setQuality(v as ExportQuality)}
            options={QUALITY_OPTIONS}
          />
        </div>

        {/* Format */}
        <fieldset className="space-y-1.5">
          <legend className={fieldLabel}>Định dạng</legend>
          <div className="inline-flex gap-1 rounded-xl border border-white/10 bg-white/[0.02] p-1">
            {(["mp4", "webm"] as ExportFormat[]).map((f) => {
              const checked = format === f;
              return (
                <label
                  key={f}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg px-4 py-1.5 text-sm transition-colors ${
                    checked
                      ? "bg-emerald-500 font-medium text-zinc-950"
                      : "text-zinc-300 hover:bg-white/[0.06]"
                  }`}
                >
                  <input
                    type="radio"
                    name="format"
                    value={f}
                    checked={checked}
                    onChange={() => setFormat(f)}
                    className="sr-only"
                  />
                  .{f}
                </label>
              );
            })}
          </div>
        </fieldset>

        {(quality !== "original" || format !== "mp4") && (
          <p className="text-xs text-zinc-500">
            Lưu ý: việc re-encode chất lượng và định dạng được xử lý phía server.
            Link tải sẽ phản ánh lựa chọn của bạn khi server hỗ trợ.
          </p>
        )}
      </div>

      {/* Download actions */}
      <div className="mt-6 flex flex-wrap gap-3">
        <a
          href={isReady ? `${downloadUrl}&quality=${quality}&format=${format}` : undefined}
          download={`${project?.title ?? projectId}.${format}`}
          aria-disabled={!isReady}
          className={downloadBtn}
        >
          <DownloadSimple size={18} weight="bold" />
          Tải {format.toUpperCase()}
        </a>

        <a
          href={isReady ? srtUrl : undefined}
          download={`${project?.title ?? projectId}.srt`}
          aria-disabled={!isReady}
          className={srtBtn}
        >
          <FileText size={18} />
          Tải SRT
        </a>

        <button type="button" onClick={() => void handleCopyLink()} className={`${btnGhost} px-5 py-2.5`}>
          {copied ? <Check size={18} weight="bold" className="text-emerald-400" /> : <LinkSimple size={18} />}
          {copied ? "Đã sao chép" : "Sao chép link"}
        </button>
      </div>

      {/* Project metadata */}
      {project && (
        <div className="mt-8 space-y-1 border-t border-white/10 pt-6 text-xs text-zinc-500">
          <p>Mã dự án: {project.short_id}</p>
          <p>Skill: {project.skill}</p>
          <p>Tạo lúc: {new Date(project.created_at).toLocaleString()}</p>
        </div>
      )}
    </div>
  );
}
