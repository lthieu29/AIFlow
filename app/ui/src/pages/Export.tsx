/**
 * Export page — final video preview + download.
 *
 * Shows an HTML5 video player for the rendered final.mp4,
 * download buttons for the video and SRT subtitle,
 * basic export quality options, and a copy-link button.
 */

import { useState, useEffect, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { apiClient } from "../api/client";

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
        setError(
          err instanceof Error ? err.message : "Failed to load project."
        );
      })
      .finally(() => setLoading(false));
  }, [projectId]);

  // ─── Derived URLs ──────────────────────────────────────────────────────────

  /** Streaming URL for the video player */
  const videoSrc = projectId ? `/api/projects/${projectId}/output` : "";

  /** Download URL — same endpoint, browser will prompt save */
  const downloadUrl = projectId
    ? `/api/projects/${projectId}/output?download=1`
    : "";

  /** SRT subtitle download */
  const srtUrl = projectId ? `/api/projects/${projectId}/srt` : "";

  /** Shareable link (localhost — for copy-link UX) */
  const shareUrl = typeof window !== "undefined"
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
      <div className="p-8 text-gray-500" aria-live="polite">
        Loading project…
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
          ← Back to home
        </Link>
      </div>
    );
  }

  const isReady = project?.status === "done";

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link
          to={`/timeline/${projectId ?? ""}`}
          className="text-sm text-blue-600 hover:underline"
        >
          ← Back to timeline
        </Link>
        <h1 className="text-2xl font-bold mt-2">
          {project?.title ?? projectId}
        </h1>
        <p className="text-xs text-gray-400 mt-0.5">
          Status:{" "}
          <span
            className={
              isReady
                ? "text-green-600 font-medium"
                : "text-yellow-600 font-medium"
            }
          >
            {project?.status ?? "unknown"}
          </span>
        </p>
      </div>

      {/* Not ready notice */}
      {!isReady && (
        <div
          role="status"
          className="mb-6 rounded border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-800"
        >
          The video is not ready yet. Go back to the{" "}
          <Link
            to={`/timeline/${projectId ?? ""}`}
            className="underline font-medium"
          >
            timeline
          </Link>{" "}
          and click "Generate Video".
        </div>
      )}

      {/* Video player */}
      <div className="rounded-xl overflow-hidden bg-black aspect-video mb-6 shadow-lg">
        {isReady ? (
          <video
            ref={videoRef}
            src={videoSrc}
            controls
            playsInline
            preload="metadata"
            className="w-full h-full"
            aria-label={`Preview of ${project?.title ?? "project"}`}
          >
            <track kind="captions" src={srtUrl} label="Vietnamese" default />
            Your browser does not support the video element.
          </video>
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-500 text-sm">
            Video not available yet
          </div>
        )}
      </div>

      {/* Export options */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 mb-6 space-y-4">
        <h2 className="text-sm font-semibold text-gray-700">Export options</h2>

        {/* Quality */}
        <div>
          <label htmlFor="quality" className="block text-xs font-medium text-gray-600 mb-1">
            Quality
          </label>
          <select
            id="quality"
            value={quality}
            onChange={(e) => setQuality(e.target.value as ExportQuality)}
            className="border border-gray-200 rounded px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            <option value="original">Original (as rendered)</option>
            <option value="1080p">1080p</option>
            <option value="720p">720p</option>
            <option value="480p">480p</option>
          </select>
        </div>

        {/* Format */}
        <div>
          <fieldset>
            <legend className="text-xs font-medium text-gray-600 mb-1">Format</legend>
            <div className="flex gap-3">
              {(["mp4", "webm"] as ExportFormat[]).map((f) => (
                <label
                  key={f}
                  className={`flex items-center gap-2 border rounded px-3 py-1.5 cursor-pointer text-sm transition-colors ${
                    format === f
                      ? "border-blue-500 bg-blue-50 font-medium"
                      : "border-gray-200 hover:border-gray-400"
                  }`}
                >
                  <input
                    type="radio"
                    name="format"
                    value={f}
                    checked={format === f}
                    onChange={() => setFormat(f)}
                    className="sr-only"
                  />
                  .{f}
                </label>
              ))}
            </div>
          </fieldset>
        </div>

        {/* Note about quality/format */}
        {(quality !== "original" || format !== "mp4") && (
          <p className="text-xs text-gray-400">
            Note: quality and format re-encoding is handled server-side. The
            download link will reflect your selection when the server supports
            it.
          </p>
        )}
      </div>

      {/* Download actions */}
      <div className="flex flex-wrap gap-3">
        {/* Download video */}
        <a
          href={
            isReady
              ? `${downloadUrl}&quality=${quality}&format=${format}`
              : undefined
          }
          download={`${project?.title ?? projectId}.${format}`}
          aria-disabled={!isReady}
          className={`inline-flex items-center gap-2 px-5 py-2.5 rounded text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
            isReady
              ? "bg-blue-600 text-white hover:bg-blue-700"
              : "bg-gray-200 text-gray-400 cursor-not-allowed pointer-events-none"
          }`}
        >
          <span aria-hidden="true">⬇</span>
          Download {format.toUpperCase()}
        </a>

        {/* Download SRT */}
        <a
          href={isReady ? srtUrl : undefined}
          download={`${project?.title ?? projectId}.srt`}
          aria-disabled={!isReady}
          className={`inline-flex items-center gap-2 px-5 py-2.5 border rounded text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 ${
            isReady
              ? "border-gray-300 text-gray-700 hover:bg-gray-50"
              : "border-gray-200 text-gray-400 cursor-not-allowed pointer-events-none"
          }`}
        >
          <span aria-hidden="true">📄</span>
          Download SRT
        </a>

        {/* Copy link */}
        <button
          type="button"
          onClick={() => void handleCopyLink()}
          className="inline-flex items-center gap-2 px-5 py-2.5 border border-gray-300 rounded text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2"
        >
          <span aria-hidden="true">{copied ? "✓" : "🔗"}</span>
          {copied ? "Copied!" : "Copy link"}
        </button>
      </div>

      {/* Project metadata */}
      {project && (
        <div className="mt-8 border-t border-gray-100 pt-6 text-xs text-gray-400 space-y-1">
          <p>Project ID: {project.short_id}</p>
          <p>Skill: {project.skill}</p>
          <p>Created: {new Date(project.created_at).toLocaleString()}</p>
        </div>
      )}
    </div>
  );
}
