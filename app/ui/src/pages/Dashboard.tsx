/**
 * Dashboard page — list all projects with status, actions (open, delete).
 */

import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Plus,
  Trash,
  FilmSlate,
  Clock,
  CheckCircle,
  Spinner,
  WarningCircle,
} from "@phosphor-icons/react";
import { apiClient } from "../api/client";
import { btnPrimary, btnGhost, btnDanger, card } from "../components/ui";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ProjectSummary {
  id: number;
  short_id: string;
  name: string;
  status: string;
  skill: string;
  scene_count: number;
  created_at: string;
  updated_at: string;
}

const STATUS_MAP: Record<string, { label: string; cls: string; icon: typeof CheckCircle }> = {
  done: { label: "Hoàn tất", cls: "text-emerald-400", icon: CheckCircle },
  generating: { label: "Đang tạo", cls: "text-amber-400", icon: Spinner },
  draft: { label: "Nháp", cls: "text-zinc-400", icon: Clock },
  failed: { label: "Thất bại", cls: "text-rose-400", icon: WarningCircle },
};

// ─── Component ────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get<ProjectSummary[]>("/projects");
      setProjects(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không tải được danh sách dự án.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchProjects();
  }, [fetchProjects]);

  async function handleDelete(id: number, name: string) {
    if (!confirm(`Xóa dự án "${name}"? Hành động này không thể hoàn tác.`)) return;
    setDeleting(id);
    try {
      await apiClient.delete(`/projects/${id}`);
      setProjects((prev) => prev.filter((p) => p.id !== id));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Không xóa được dự án.");
    } finally {
      setDeleting(null);
    }
  }

  // ─── Render ──────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="px-6 py-10 text-sm text-zinc-500" aria-live="polite">
        Đang tải danh sách dự án…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-zinc-50">
            <FilmSlate size={28} weight="duotone" className="text-emerald-400" />
            Dự án của tôi
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            {projects.length} dự án
          </p>
        </div>
        <Link to="/new-project" className={btnPrimary}>
          <Plus size={16} weight="bold" />
          Dự án mới
        </Link>
      </div>

      {/* Error */}
      {error && (
        <div
          role="alert"
          className="mb-4 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
        >
          <WarningCircle size={18} weight="fill" className="text-rose-400" />
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && projects.length === 0 && !error && (
        <div className="rounded-2xl border border-dashed border-white/10 px-6 py-16 text-center">
          <FilmSlate size={48} weight="thin" className="mx-auto text-zinc-600" />
          <p className="mt-4 text-sm text-zinc-500">
            Chưa có dự án nào. Tạo dự án đầu tiên để bắt đầu.
          </p>
          <Link to="/new-project" className={`${btnPrimary} mt-4 inline-flex`}>
            <Plus size={16} weight="bold" />
            Tạo dự án
          </Link>
        </div>
      )}

      {/* Project list */}
      {projects.length > 0 && (
        <div className="space-y-3">
          {projects.map((project) => {
            const statusInfo = STATUS_MAP[project.status] ?? STATUS_MAP.draft;
            const StatusIcon = statusInfo.icon;
            const isDeleting = deleting === project.id;

            return (
              <div
                key={project.id}
                className={`${card} flex items-center gap-4 p-4 transition-colors hover:border-white/15`}
              >
                {/* Info */}
                <div className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => navigate(`/timeline/${project.short_id}`)}
                    className="truncate text-left text-base font-medium text-zinc-100 hover:text-emerald-300"
                  >
                    {project.name}
                  </button>
                  <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-zinc-500">
                    <span className={`inline-flex items-center gap-1 ${statusInfo.cls}`}>
                      <StatusIcon size={13} weight="fill" />
                      {statusInfo.label}
                    </span>
                    {project.skill && (
                      <span className="rounded bg-white/[0.05] px-1.5 py-0.5">
                        {project.skill}
                      </span>
                    )}
                    <span>{project.scene_count} cảnh</span>
                    <span>
                      {new Date(project.created_at).toLocaleDateString("vi-VN", {
                        day: "2-digit",
                        month: "2-digit",
                        year: "numeric",
                      })}
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex shrink-0 items-center gap-2">
                  <Link
                    to={`/timeline/${project.short_id}`}
                    className={btnGhost}
                  >
                    Mở
                  </Link>
                  {project.status === "done" && (
                    <Link
                      to={`/export/${project.short_id}`}
                      className={btnGhost}
                    >
                      Xuất
                    </Link>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDelete(project.id, project.name)}
                    disabled={isDeleting}
                    className={btnDanger}
                    aria-label={`Xóa dự án ${project.name}`}
                  >
                    <Trash size={16} weight="bold" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
