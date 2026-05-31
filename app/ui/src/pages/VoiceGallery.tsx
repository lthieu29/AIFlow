/**
 * VoiceGallery page — browse, preview, upload, and delete TTS voices.
 *
 * Features:
 *  - Lists all preset + custom voices from GET /api/tts/voices
 *  - Voice cards: name, language, gender, backend, description
 *  - Demo audio playback (plays demo_audio_path if available)
 *  - Filter by: preset/custom, language, gender
 *  - Upload custom voice zip (POST /api/tts/voices/custom)
 *  - Delete custom voice with confirmation dialog (DELETE /api/tts/voices/custom/{id})
 */

import { useState, useEffect, useRef, useCallback, ChangeEvent } from "react";
import { Link } from "react-router-dom";
import { useVoiceStore } from "../store";
import { uploadCustomVoice, deleteCustomVoice } from "../api/client";
import type { VoiceInfo } from "../api/client";

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
  if (gender === "male") return "bg-blue-100 text-blue-700";
  if (gender === "female") return "bg-pink-100 text-pink-700";
  return "bg-gray-100 text-gray-600";
}

// ─── Delete confirmation dialog ───────────────────────────────────────────────

interface DeleteDialogProps {
  voice: VoiceInfo;
  onConfirm: () => void;
  onCancel: () => void;
  deleting: boolean;
}

function DeleteDialog({ voice, onConfirm, onCancel, deleting }: DeleteDialogProps) {
  // Trap focus inside dialog
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="bg-white rounded-xl shadow-xl max-w-sm w-full mx-4 p-6">
        <h2 id="delete-dialog-title" className="text-base font-semibold text-gray-900 mb-2">
          Xóa giọng nói?
        </h2>
        <p id="delete-dialog-desc" className="text-sm text-gray-600 mb-6">
          Bạn có chắc muốn xóa{" "}
          <span className="font-medium text-gray-900">{voice.name}</span> không?
          Hành động này không thể hoàn tác.
        </p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 disabled:opacity-50"
          >
            Hủy
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={deleting}
            className="px-4 py-2 text-sm bg-red-600 text-white rounded hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
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
      className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col gap-3 hover:shadow-sm transition-shadow"
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-gray-900 truncate">
            {voice.name}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">{voice.language}</p>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {voice.is_custom && (
            <span
              aria-label="Giọng tùy chỉnh"
              className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium"
            >
              Tùy chỉnh
            </span>
          )}
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${genderBadgeClass(voice.gender)}`}
          >
            {genderLabel(voice.gender)}
          </span>
        </div>
      </div>

      {/* Description */}
      {voice.description && (
        <p className="text-xs text-gray-500 leading-relaxed line-clamp-2">
          {voice.description}
        </p>
      )}

      {/* Backend badge */}
      <p className="text-xs text-gray-400">
        Nền tảng:{" "}
        <span className="font-medium text-gray-600">{backendLabel(voice.backend)}</span>
      </p>

      {/* Actions row */}
      <div className="flex items-center gap-2 mt-auto pt-1">
        {/* Demo playback */}
        {hasDemo ? (
          isPlaying ? (
            <button
              type="button"
              onClick={onStop}
              aria-label={`Dừng demo của ${voice.name}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-1"
            >
              <span aria-hidden="true">⏹</span>
              Dừng
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onPlay(voice)}
              aria-label={`Phát demo của ${voice.name}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-50 border border-blue-200 text-blue-700 rounded hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-1"
            >
              <span aria-hidden="true">▶</span>
              Demo
            </button>
          )
        ) : (
          <span className="text-xs text-gray-300 italic">Không có demo</span>
        )}

        {/* Delete (custom voices only) */}
        {voice.is_custom && (
          <button
            type="button"
            onClick={() => onDelete(voice)}
            aria-label={`Xóa giọng ${voice.name}`}
            className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 text-xs border border-red-200 text-red-600 rounded hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-1"
          >
            <span aria-hidden="true">🗑</span>
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
      setError(
        err instanceof Error ? err.message : "Tải lên thất bại. Vui lòng thử lại."
      );
    } finally {
      setUploading(false);
    }
  }

  return (
    <section
      aria-labelledby="upload-heading"
      className="bg-white border border-gray-200 rounded-xl p-5"
    >
      <h2 id="upload-heading" className="text-sm font-semibold text-gray-800 mb-3">
        Tải lên giọng tùy chỉnh
      </h2>
      <p className="text-xs text-gray-500 mb-4">
        Tải lên gói <code className="bg-gray-100 px-1 rounded">.zip</code> được tạo
        bởi notebook huấn luyện trên Colab.
      </p>

      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        {/* File input */}
        <label className="flex-1">
          <span className="sr-only">Chọn file zip giọng nói</span>
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip"
            onChange={handleFileChange}
            disabled={uploading}
            aria-label="Chọn file zip giọng nói"
            className="block w-full text-sm text-gray-600 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border file:border-gray-300 file:text-xs file:font-medium file:bg-gray-50 file:text-gray-700 hover:file:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-1 disabled:opacity-50"
          />
        </label>

        {/* Upload button */}
        <button
          type="button"
          onClick={() => void handleUpload()}
          disabled={!file || uploading}
          aria-busy={uploading}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 whitespace-nowrap"
        >
          {uploading ? "Đang tải lên…" : "Tải lên"}
        </button>
      </div>

      {/* Selected file name */}
      {file && !uploading && (
        <p className="mt-2 text-xs text-gray-500">
          Đã chọn: <span className="font-medium">{file.name}</span> (
          {(file.size / 1024).toFixed(1)} KB)
        </p>
      )}

      {/* Progress indicator */}
      {uploading && (
        <p role="status" aria-live="polite" className="mt-2 text-xs text-blue-600">
          Đang tải lên, vui lòng đợi…
        </p>
      )}

      {/* Success */}
      {success && (
        <p role="status" aria-live="polite" className="mt-2 text-xs text-green-700 bg-green-50 border border-green-200 rounded px-3 py-2">
          ✓ {success}
        </p>
      )}

      {/* Error */}
      {error && (
        <p role="alert" aria-live="assertive" className="mt-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
          ✗ {error}
        </p>
      )}
    </section>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function VoiceGallery() {
  const { voices, loading, error, fetchVoices } = useVoiceStore();

  // Filters
  const [typeFilter, setTypeFilter] = useState<VoiceTypeFilter>("all");
  const [languageFilter, setLanguageFilter] = useState<string>("all");
  const [genderFilter, setGenderFilter] = useState<GenderFilter>("all");

  // Audio playback
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);

  // Delete dialog
  const [voiceToDelete, setVoiceToDelete] = useState<VoiceInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Load voices on mount
  useEffect(() => {
    void fetchVoices();
  }, [fetchVoices]);

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  // ─── Derived data ──────────────────────────────────────────────────────────

  const languages = Array.from(
    new Set(voices.map((v) => v.language))
  ).sort();

  const filteredVoices = voices.filter((v) => {
    if (typeFilter === "preset" && v.is_custom) return false;
    if (typeFilter === "custom" && !v.is_custom) return false;
    if (languageFilter !== "all" && v.language !== languageFilter) return false;
    if (genderFilter !== "all" && v.gender !== genderFilter) return false;
    return true;
  });

  const presetCount = voices.filter((v) => !v.is_custom).length;
  const customCount = voices.filter((v) => v.is_custom).length;

  // ─── Audio playback ────────────────────────────────────────────────────────

  const handlePlay = useCallback((voice: VoiceInfo) => {
    if (!voice.demo_audio_path) return;

    // Stop any currently playing audio
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
      // Stop audio if the deleted voice was playing
      if (playingVoiceId === voiceToDelete.id) {
        handleStop();
      }
      void fetchVoices();
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Không xóa được giọng nói."
      );
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
    <div className="max-w-5xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link to="/" className="text-sm text-blue-600 hover:underline">
          ← Về trang chủ
        </Link>
        <h1 className="text-2xl font-bold mt-2">Thư viện giọng nói</h1>
        <p className="text-gray-500 text-sm mt-1">
          Duyệt và quản lý giọng nói TTS. Giọng có sẵn (preset) là tích hợp sẵn;
          giọng tùy chỉnh là các model bạn tự huấn luyện và tải lên.
        </p>
      </div>

      {/* Upload panel */}
      <div className="mb-8">
        <UploadPanel onUploaded={() => void fetchVoices()} />
      </div>

      {/* Delete error (outside dialog, shown after dialog closes) */}
      {deleteError && !voiceToDelete && (
        <div role="alert" className="mb-4 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
          {deleteError}
        </div>
      )}

      {/* Filters */}
      <div
        className="mb-6 flex flex-wrap gap-4 items-end"
        role="group"
        aria-label="Lọc giọng nói"
      >
        {/* Type filter */}
        <div>
          <label htmlFor="filter-type" className="block text-xs font-medium text-gray-600 mb-1">
            Loại
          </label>
          <select
            id="filter-type"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as VoiceTypeFilter)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            <option value="all">Tất cả ({voices.length})</option>
            <option value="preset">Có sẵn ({presetCount})</option>
            <option value="custom">Tùy chỉnh ({customCount})</option>
          </select>
        </div>

        {/* Language filter */}
        <div>
          <label htmlFor="filter-language" className="block text-xs font-medium text-gray-600 mb-1">
            Ngôn ngữ
          </label>
          <select
            id="filter-language"
            value={languageFilter}
            onChange={(e) => setLanguageFilter(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            <option value="all">Tất cả ngôn ngữ</option>
            {languages.map((lang) => (
              <option key={lang} value={lang}>
                {lang}
              </option>
            ))}
          </select>
        </div>

        {/* Gender filter */}
        <div>
          <label htmlFor="filter-gender" className="block text-xs font-medium text-gray-600 mb-1">
            Giới tính
          </label>
          <select
            id="filter-gender"
            value={genderFilter}
            onChange={(e) => setGenderFilter(e.target.value as GenderFilter)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            <option value="all">Tất cả giới tính</option>
            <option value="male">Nam</option>
            <option value="female">Nữ</option>
            <option value="neutral">Trung tính</option>
          </select>
        </div>

        {/* Reset filters */}
        {(typeFilter !== "all" || languageFilter !== "all" || genderFilter !== "all") && (
          <button
            type="button"
            onClick={() => {
              setTypeFilter("all");
              setLanguageFilter("all");
              setGenderFilter("all");
            }}
            className="text-xs text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-1 rounded"
          >
            Đặt lại bộ lọc
          </button>
        )}
      </div>

      {/* Voice list */}
      {loading && (
        <p role="status" aria-live="polite" className="text-sm text-gray-400 py-8 text-center">
          Đang tải giọng nói…
        </p>
      )}

      {error && !loading && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 mb-4">
          {error}
          <button
            type="button"
            onClick={() => void fetchVoices()}
            className="ml-3 underline hover:no-underline focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-1 rounded"
          >
            Thử lại
          </button>
        </div>
      )}

      {!loading && !error && filteredVoices.length === 0 && (
        <p className="text-sm text-gray-400 py-8 text-center">
          {voices.length === 0
            ? "Không tìm thấy giọng nói nào. Hãy đảm bảo server đang chạy."
            : "Không có giọng nói nào khớp bộ lọc hiện tại."}
        </p>
      )}

      {!loading && filteredVoices.length > 0 && (
        <>
          <p className="text-xs text-gray-400 mb-3" aria-live="polite">
            Hiển thị {filteredVoices.length} trong tổng {voices.length} giọng
          </p>
          <ul
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
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
