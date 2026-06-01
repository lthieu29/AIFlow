/**
 * VoiceGallery page — browse, preview, upload, and delete TTS voices.
 *
 *  - Lists all preset + custom voices from GET /api/tts/voices
 *  - Voice cards: name, language, gender, backend, description
 *  - Demo audio playback (plays demo_audio_path if available)
 *  - Filter by: preset/custom, language, gender
 *  - Upload custom voice zip (POST /api/tts/voices/custom)
 *  - Delete custom voice with confirmation dialog (DELETE /api/tts/voices/custom/{id})
 */

import { useState, useEffect, useRef, useCallback, type ChangeEvent } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  Play,
  Stop,
  Trash,
  UploadSimple,
  WarningCircle,
  CheckCircle,
  Sparkle,
} from "@phosphor-icons/react";
import { useVoiceStore } from "../store";
import { uploadCustomVoice, deleteCustomVoice } from "../api/client";
import type { VoiceInfo } from "../api/client";
import Combobox, { type ComboOption } from "../components/Combobox";
import { btnPrimary, btnGhost, btnDanger, card, fieldLabel } from "../components/ui";

// ─── Filter types ─────────────────────────────────────────────────────────────

type VoiceTypeFilter = "all" | "preset" | "custom";
type GenderFilter = "all" | "male" | "female" | "neutral";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function genderLabel(gender: string): string {
  if (gender === "male") return "Nam";
  if (gender === "female") return "Nữ";
  if (gender === "neutral") return "Trung tính";
  return gender;
}

function backendLabel(backend: string): string {
  if (backend === "vieneu") return "VieNeu";
  if (backend === "edge_tts") return "Edge TTS";
  return backend;
}

function genderBadgeClass(gender: string): string {
  if (gender === "male") return "bg-sky-500/15 text-sky-300";
  if (gender === "female") return "bg-pink-500/15 text-pink-300";
  return "bg-white/[0.06] text-zinc-400";
}

// ─── Delete confirmation dialog ───────────────────────────────────────────────

interface DeleteDialogProps {
  voice: VoiceInfo;
  onConfirm: () => void;
  onCancel: () => void;
  deleting: boolean;
}

function DeleteDialog({ voice, onConfirm, onCancel, deleting }: DeleteDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
  }, []);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-dialog-title"
      aria-describedby="delete-dialog-desc"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="pop-in w-full max-w-sm rounded-2xl border border-white/10 bg-zinc-900 p-6 shadow-2xl shadow-black/60">
        <h2 id="delete-dialog-title" className="text-base font-semibold text-zinc-50">
          Xóa giọng nói?
        </h2>
        <p id="delete-dialog-desc" className="mt-2 text-sm text-zinc-400">
          Bạn có chắc muốn xóa{" "}
          <span className="font-medium text-zinc-100">{voice.name}</span> không? Hành
          động này không thể hoàn tác.
        </p>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onCancel} disabled={deleting} className={btnGhost}>
            Hủy
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={deleting}
            className={btnDanger}
          >
            <Trash size={16} weight="bold" />
            {deleting ? "Đang xóa…" : "Xóa"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Voice card ───────────────────────────────────────────────────────────────

interface VoiceCardProps {
  voice: VoiceInfo;
  isPlaying: boolean;
  onPlay: (voice: VoiceInfo) => void;
  onStop: () => void;
  onDelete: (voice: VoiceInfo) => void;
}

function VoiceCard({ voice, isPlaying, onPlay, onStop, onDelete }: VoiceCardProps) {
  const hasDemo = Boolean(voice.demo_audio_path);

  return (
    <article
      aria-label={`Voice: ${voice.name}`}
      className={`${card} flex h-full flex-col gap-3 p-4 transition-colors hover:border-white/20`}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-zinc-50">{voice.name}</h3>
          <p className="mt-0.5 text-xs text-zinc-500">{voice.language}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {voice.is_custom && (
            <span
              aria-label="Giọng tùy chỉnh"
              className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-300"
            >
              <Sparkle size={11} weight="fill" />
              Tùy chỉnh
            </span>
          )}
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${genderBadgeClass(voice.gender)}`}
          >
            {genderLabel(voice.gender)}
          </span>
        </div>
      </div>

      {/* Description */}
      {voice.description && (
        <p className="line-clamp-2 text-xs leading-relaxed text-zinc-500">
          {voice.description}
        </p>
      )}

      {/* Backend */}
      <p className="text-xs text-zinc-500">
        Nền tảng:{" "}
        <span className="font-medium text-zinc-300">{backendLabel(voice.backend)}</span>
      </p>

      {/* Actions row */}
      <div className="mt-auto flex items-center gap-2 pt-1">
        {hasDemo ? (
          isPlaying ? (
            <button
              type="button"
              onClick={onStop}
              aria-label={`Dừng demo của ${voice.name}`}
              className={`${btnGhost} px-3 py-1.5 text-xs`}
            >
              <Stop size={14} weight="fill" />
              Dừng
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onPlay(voice)}
              aria-label={`Phát demo của ${voice.name}`}
              className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 transition-colors hover:bg-emerald-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
            >
              <Play size={14} weight="fill" />
              Demo
            </button>
          )
        ) : (
          <span className="text-xs italic text-zinc-600">Không có demo</span>
        )}

        {voice.is_custom && (
          <button
            type="button"
            onClick={() => onDelete(voice)}
            aria-label={`Xóa giọng ${voice.name}`}
            className={`${btnDanger} ml-auto px-3 py-1.5 text-xs`}
          >
            <Trash size={14} />
            Xóa
          </button>
        )}
      </div>
    </article>
  );
}

// ─── Upload panel ─────────────────────────────────────────────────────────────

interface UploadPanelProps {
  onUploaded: () => void;
}

function UploadPanel({ onUploaded }: UploadPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] ?? null;
    setFile(selected);
    setSuccess(null);
    setError(null);
  }

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setSuccess(null);
    setError(null);

    try {
      const result = await uploadCustomVoice(file);
      setSuccess(`Đã tải lên giọng "${result.name}" thành công (trạng thái: ${result.status}).`);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tải lên thất bại. Vui lòng thử lại.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <section aria-labelledby="upload-heading" className={`${card} p-5`}>
      <h2 id="upload-heading" className="text-sm font-semibold text-zinc-200">
        Tải lên giọng tùy chỉnh
      </h2>
      <p className="mt-1 text-xs text-zinc-500">
        Tải lên gói <code className="rounded bg-white/[0.06] px-1 text-zinc-300">.zip</code>{" "}
        được tạo bởi notebook huấn luyện trên Colab.
      </p>

      <div className="mt-4 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
        <label className="flex-1">
          <span className="sr-only">Chọn file zip giọng nói</span>
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip"
            onChange={handleFileChange}
            disabled={uploading}
            aria-label="Chọn file zip giọng nói"
            className="block w-full text-sm text-zinc-400 file:mr-3 file:rounded-lg file:border-0 file:bg-white/[0.06] file:px-3 file:py-2 file:text-xs file:font-medium file:text-zinc-200 hover:file:bg-white/[0.1] focus:outline-none disabled:opacity-40"
          />
        </label>

        <button
          type="button"
          onClick={() => void handleUpload()}
          disabled={!file || uploading}
          aria-busy={uploading}
          className={btnPrimary}
        >
          <UploadSimple size={16} weight="bold" />
          {uploading ? "Đang tải lên…" : "Tải lên"}
        </button>
      </div>

      {file && !uploading && (
        <p className="mt-2 text-xs text-zinc-500">
          Đã chọn: <span className="font-medium text-zinc-300">{file.name}</span> (
          {(file.size / 1024).toFixed(1)} KB)
        </p>
      )}

      {uploading && (
        <p role="status" aria-live="polite" className="mt-2 text-xs text-emerald-400">
          Đang tải lên, vui lòng đợi…
        </p>
      )}

      {success && (
        <p
          role="status"
          aria-live="polite"
          className="mt-3 flex items-start gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200"
        >
          <CheckCircle size={15} weight="fill" className="mt-0.5 shrink-0 text-emerald-400" />
          {success}
        </p>
      )}

      {error && (
        <p
          role="alert"
          aria-live="assertive"
          className="mt-3 flex items-start gap-1.5 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
        >
          <WarningCircle size={15} weight="fill" className="mt-0.5 shrink-0 text-rose-400" />
          {error}
        </p>
      )}
    </section>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function VoiceGallery() {
  const { voices, loading, error, fetchVoices } = useVoiceStore();

  const [typeFilter, setTypeFilter] = useState<VoiceTypeFilter>("all");
  const [languageFilter, setLanguageFilter] = useState<string>("all");
  const [genderFilter, setGenderFilter] = useState<GenderFilter>("all");

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);

  const [voiceToDelete, setVoiceToDelete] = useState<VoiceInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    void fetchVoices();
  }, [fetchVoices]);

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  // ─── Derived data ──────────────────────────────────────────────────────────

  const languages = Array.from(new Set(voices.map((v) => v.language))).sort();

  const filteredVoices = voices.filter((v) => {
    if (typeFilter === "preset" && v.is_custom) return false;
    if (typeFilter === "custom" && !v.is_custom) return false;
    if (languageFilter !== "all" && v.language !== languageFilter) return false;
    if (genderFilter !== "all" && v.gender !== genderFilter) return false;
    return true;
  });

  const presetCount = voices.filter((v) => !v.is_custom).length;
  const customCount = voices.filter((v) => v.is_custom).length;

  const typeOptions: ComboOption[] = [
    { value: "all", label: `Tất cả (${voices.length})` },
    { value: "preset", label: `Có sẵn (${presetCount})` },
    { value: "custom", label: `Tùy chỉnh (${customCount})` },
  ];

  const languageOptions: ComboOption[] = [
    { value: "all", label: "Tất cả ngôn ngữ" },
    ...languages.map((lang) => ({ value: lang, label: lang })),
  ];

  const genderOptions: ComboOption[] = [
    { value: "all", label: "Tất cả giới tính" },
    { value: "male", label: "Nam" },
    { value: "female", label: "Nữ" },
    { value: "neutral", label: "Trung tính" },
  ];

  const hasFilters =
    typeFilter !== "all" || languageFilter !== "all" || genderFilter !== "all";

  // ─── Audio playback ────────────────────────────────────────────────────────

  const handlePlay = useCallback((voice: VoiceInfo) => {
    if (!voice.demo_audio_path) return;

    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
    }

    const audio = new Audio(`/api${voice.demo_audio_path}`);
    audioRef.current = audio;
    setPlayingVoiceId(voice.id);

    audio.addEventListener("ended", () => setPlayingVoiceId(null));
    audio.addEventListener("error", () => setPlayingVoiceId(null));

    void audio.play().catch(() => setPlayingVoiceId(null));
  }, []);

  const handleStop = useCallback(() => {
    audioRef.current?.pause();
    setPlayingVoiceId(null);
  }, []);

  // ─── Delete ────────────────────────────────────────────────────────────────

  function handleDeleteRequest(voice: VoiceInfo) {
    setVoiceToDelete(voice);
    setDeleteError(null);
  }

  async function handleDeleteConfirm() {
    if (!voiceToDelete) return;
    setDeleting(true);
    setDeleteError(null);

    try {
      await deleteCustomVoice(voiceToDelete.id);
      setVoiceToDelete(null);
      if (playingVoiceId === voiceToDelete.id) {
        handleStop();
      }
      void fetchVoices();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Không xóa được giọng nói.");
    } finally {
      setDeleting(false);
    }
  }

  function handleDeleteCancel() {
    setVoiceToDelete(null);
    setDeleteError(null);
  }

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      {/* Header */}
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300">
        <ArrowLeft size={16} />
        Về trang chủ
      </Link>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight text-zinc-50">
        Thư viện giọng nói
      </h1>
      <p className="mt-1 max-w-2xl text-sm text-zinc-400">
        Duyệt và quản lý giọng nói TTS. Giọng có sẵn (preset) là tích hợp sẵn; giọng
        tùy chỉnh là các model bạn tự huấn luyện và tải lên.
      </p>

      {/* Upload panel */}
      <div className="mt-8">
        <UploadPanel onUploaded={() => void fetchVoices()} />
      </div>

      {/* Delete error (outside dialog) */}
      {deleteError && !voiceToDelete && (
        <div
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
        >
          <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-rose-400" />
          {deleteError}
        </div>
      )}

      {/* Filters */}
      <div className="mt-8 flex flex-wrap items-end gap-4" role="group" aria-label="Lọc giọng nói">
        <div className="w-44 space-y-1.5">
          <label htmlFor="filter-type" className={fieldLabel}>
            Loại
          </label>
          <Combobox
            id="filter-type"
            value={typeFilter}
            onChange={(v) => setTypeFilter(v as VoiceTypeFilter)}
            options={typeOptions}
          />
        </div>

        <div className="w-44 space-y-1.5">
          <label htmlFor="filter-language" className={fieldLabel}>
            Ngôn ngữ
          </label>
          <Combobox
            id="filter-language"
            value={languageFilter}
            onChange={setLanguageFilter}
            options={languageOptions}
          />
        </div>

        <div className="w-44 space-y-1.5">
          <label htmlFor="filter-gender" className={fieldLabel}>
            Giới tính
          </label>
          <Combobox
            id="filter-gender"
            value={genderFilter}
            onChange={(v) => setGenderFilter(v as GenderFilter)}
            options={genderOptions}
          />
        </div>

        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              setTypeFilter("all");
              setLanguageFilter("all");
              setGenderFilter("all");
            }}
            className="rounded text-sm text-emerald-400 hover:text-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60"
          >
            Đặt lại bộ lọc
          </button>
        )}
      </div>

      {/* Voice list */}
      {loading && (
        <p role="status" aria-live="polite" className="py-12 text-center text-sm text-zinc-500">
          Đang tải giọng nói…
        </p>
      )}

      {error && !loading && (
        <div
          role="alert"
          className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
        >
          <WarningCircle size={18} weight="fill" className="shrink-0 text-rose-400" />
          {error}
          <button
            type="button"
            onClick={() => void fetchVoices()}
            className="ml-1 underline hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
          >
            Thử lại
          </button>
        </div>
      )}

      {!loading && !error && filteredVoices.length === 0 && (
        <p className="py-12 text-center text-sm text-zinc-500">
          {voices.length === 0
            ? "Không tìm thấy giọng nói nào. Hãy đảm bảo server đang chạy."
            : "Không có giọng nói nào khớp bộ lọc hiện tại."}
        </p>
      )}

      {!loading && filteredVoices.length > 0 && (
        <>
          <p className="mb-3 mt-6 text-xs text-zinc-500" aria-live="polite">
            Hiển thị {filteredVoices.length} trong tổng {voices.length} giọng
          </p>
          <ul
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
            aria-label="Danh sách giọng nói"
          >
            {filteredVoices.map((voice) => (
              <li key={voice.id}>
                <VoiceCard
                  voice={voice}
                  isPlaying={playingVoiceId === voice.id}
                  onPlay={handlePlay}
                  onStop={handleStop}
                  onDelete={handleDeleteRequest}
                />
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Delete confirmation dialog */}
      {voiceToDelete && (
        <DeleteDialog
          voice={voiceToDelete}
          onConfirm={() => void handleDeleteConfirm()}
          onCancel={handleDeleteCancel}
          deleting={deleting}
        />
      )}
    </div>
  );
}
