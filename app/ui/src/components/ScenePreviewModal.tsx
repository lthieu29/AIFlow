/**
 * ScenePreviewModal — review the scene list a ContentAdapter would produce
 * before committing a project.
 *
 * Backed by the `/api/content/parse` endpoint via `parseContent()`.  The
 * modal is a dumb display: it does not mutate the parent form's state.
 * Closing or pressing "Tạo dự án" returns control to NewProject, which is
 * responsible for the actual POST.
 */

import { useEffect, useState } from "react";
import { X, Eye, WarningCircle } from "@phosphor-icons/react";
import { btnGhost, btnPrimary, card } from "./ui";
import { parseContent, type SceneListOut } from "../api/client";

interface ScenePreviewModalProps {
  open: boolean;
  adapter: string;
  inputData: Record<string, unknown> | null;
  onClose: () => void;
  onConfirm: () => void;
}

function formatNumber(value: unknown): string {
  if (typeof value !== "number") return "—";
  if (value >= 1000) return value.toLocaleString("vi-VN");
  return value.toFixed(value % 1 === 0 ? 0 : 2);
}

export default function ScenePreviewModal({
  open,
  adapter,
  inputData,
  onClose,
  onConfirm,
}: ScenePreviewModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<SceneListOut | null>(null);

  useEffect(() => {
    if (!open || !inputData) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);

    parseContent(adapter, inputData)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const detail =
          err && typeof err === "object" && "response" in err
            ? ((err as { response?: { data?: { detail?: { error?: { message?: string } } } } })
                .response?.data?.detail?.error?.message ?? null)
            : null;
        setError(detail || (err instanceof Error ? err.message : "Không phân tích được đầu vào."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, adapter, inputData]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="scene-preview-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/80 px-4 py-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={`${card} w-full max-w-3xl overflow-hidden`}>
        <header className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <h2
            id="scene-preview-title"
            className="flex items-center gap-2 text-base font-semibold text-zinc-100"
          >
            <Eye size={18} weight="duotone" className="text-emerald-400" />
            Xem trước cảnh
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng"
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-100"
          >
            <X size={18} />
          </button>
        </header>

        <div className="max-h-[60vh] overflow-y-auto px-5 py-4">
          {loading && (
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-sm text-zinc-400">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
              Đang phân tích đầu vào…
            </div>
          )}

          {error && !loading && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
            >
              <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-rose-400" />
              <div>
                <p className="font-medium">Không phân tích được</p>
                <p className="mt-0.5 text-rose-300/90">{error}</p>
                <p className="mt-1 text-xs text-rose-300/70">
                  Bạn vẫn có thể tạo dự án — adapter sẽ chạy lại khi tạo.
                </p>
              </div>
            </div>
          )}

          {data && !loading && (
            <div className="space-y-4">
              {/* Cost summary */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Số cảnh" value={data.scene_count} />
                <Stat
                  label="Tổng thời lượng"
                  value={`${formatNumber(data.estimated_cost?.total_seconds)} s`}
                />
                <Stat
                  label="Clip Veo3"
                  value={formatNumber(
                    data.estimated_cost?.veo3_clips ?? data.estimated_cost?.clip_count,
                  )}
                />
                <Stat
                  label="Credit ước tính"
                  value={formatNumber(
                    data.estimated_cost?.estimated_credits ?? data.estimated_cost?.credits,
                  )}
                />
              </div>

              {/* Scene list */}
              <ol className="space-y-2">
                {data.scenes.map((scene) => (
                  <li
                    key={scene.order}
                    className="rounded-xl border border-white/10 bg-white/[0.02] p-3"
                  >
                    <header className="flex items-center justify-between gap-2 text-xs">
                      <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 font-medium text-emerald-300">
                        Cảnh {scene.order + 1}
                      </span>
                      <span className="text-zinc-500">
                        {formatNumber(scene.duration)} s
                        {scene.location_hint ? ` · ${scene.location_hint}` : ""}
                      </span>
                    </header>
                    {scene.narration && (
                      <p className="mt-2 text-sm leading-relaxed text-zinc-200">
                        {scene.narration}
                      </p>
                    )}
                    {scene.prompt && (
                      <p className="mt-1.5 line-clamp-3 text-xs leading-relaxed text-zinc-500">
                        <span className="font-medium text-zinc-400">Prompt:</span> {scene.prompt}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-white/10 bg-white/[0.02] px-5 py-3">
          <p className="text-xs text-zinc-500">
            Đây chỉ là bản xem trước — không lưu vào dự án cho tới khi bấm "Tạo dự án".
          </p>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} className={btnGhost}>
              Đóng
            </button>
            <button
              type="button"
              onClick={() => {
                onConfirm();
                onClose();
              }}
              disabled={loading}
              className={btnPrimary}
            >
              Tạo dự án
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-0.5 font-semibold text-zinc-100">{value}</p>
    </div>
  );
}
