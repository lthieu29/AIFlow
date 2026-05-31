/**
 * NewProject page — input adapter + skill picker + voice picker.
 *
 * Lets the user choose an adapter type, fill in the required input,
 * pick a skill and a TTS voice, then submit to POST /api/projects.
 */

import { useState, useEffect, FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiClient } from "../api/client";
import { useVoiceStore } from "../store";

// ─── Types ────────────────────────────────────────────────────────────────────

type AdapterName =
  | "ecommerce_product"
  | "narrative_script"
  | "blog_article"
  | "storyboard_manual";

interface AdapterMeta {
  label: string;
  description: string;
  inputType: "text" | "url" | "textarea" | "json";
  inputLabel: string;
  inputPlaceholder: string;
}

const ADAPTERS: Record<AdapterName, AdapterMeta> = {
  ecommerce_product: {
    label: "Sản phẩm thương mại điện tử",
    description: "Tạo video sản phẩm kiểu TikTok/Reels từ đường dẫn ảnh và thông tin.",
    inputType: "text",
    inputLabel: "Đường dẫn ảnh sản phẩm",
    inputPlaceholder: "storage/media/product.jpg",
  },
  narrative_script: {
    label: "Kịch bản tường thuật",
    description: "Biến một kịch bản/vlog dạng markdown thành video.",
    inputType: "textarea",
    inputLabel: "Kịch bản markdown",
    inputPlaceholder: "# Câu chuyện của tôi\n\nCảnh 1: ...",
  },
  blog_article: {
    label: "Bài viết blog",
    description: "Chuyển một URL blog hoặc markdown thành video giải thích.",
    inputType: "url",
    inputLabel: "URL bài viết",
    inputPlaceholder: "https://example.com/article",
  },
  storyboard_manual: {
    label: "Storyboard thủ công",
    description: "Cung cấp một storyboard JSON với các cảnh tự định nghĩa.",
    inputType: "json",
    inputLabel: "Storyboard JSON",
    inputPlaceholder: '{"scenes": [{"narration": "...", "visual_prompt": "..."}]}',
  },
};

const SKILLS = [
  { id: "ecommerce-fashion", label: "Thời trang TMĐT" },
];

// ─── Component ────────────────────────────────────────────────────────────────

export default function NewProject() {
  const navigate = useNavigate();
  const { voices, loading: voicesLoading, fetchVoices } = useVoiceStore();

  // Form state
  const [title, setTitle] = useState("");
  const [adapter, setAdapter] = useState<AdapterName>("ecommerce_product");
  const [inputValue, setInputValue] = useState("");
  const [skillId, setSkillId] = useState("ecommerce-fashion");
  const [voiceId, setVoiceId] = useState("");
  const [aspectRatio, setAspectRatio] = useState<"9:16" | "16:9" | "1:1">("9:16");

  // UI state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Load voices on mount
  useEffect(() => {
    fetchVoices();
  }, [fetchVoices]);

  // Set default voice once voices load
  useEffect(() => {
    if (voices.length > 0 && !voiceId) {
      const defaultVoice = voices.find((v) => v.id === "Binh") ?? voices[0];
      setVoiceId(defaultVoice.id);
    }
  }, [voices, voiceId]);

  // Reset input when adapter changes
  useEffect(() => {
    setInputValue("");
    setFieldErrors({});
  }, [adapter]);

  // ─── Validation ─────────────────────────────────────────────────────────────

  function validate(): boolean {
    const errors: Record<string, string> = {};

    if (!title.trim()) {
      errors.title = "Bắt buộc nhập tên dự án.";
    }

    if (!inputValue.trim()) {
      errors.input = `Bắt buộc nhập ${ADAPTERS[adapter].inputLabel.toLowerCase()}.`;
    } else if (ADAPTERS[adapter].inputType === "url") {
      try {
        new URL(inputValue.trim());
      } catch {
        errors.input = "Vui lòng nhập URL hợp lệ.";
      }
    } else if (ADAPTERS[adapter].inputType === "json") {
      try {
        JSON.parse(inputValue.trim());
      } catch {
        errors.input = "Vui lòng nhập JSON hợp lệ.";
      }
    }

    if (!skillId) {
      errors.skill = "Vui lòng chọn một skill.";
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  // ─── Submit ──────────────────────────────────────────────────────────────────

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!validate()) return;

    // Build adapter_input based on adapter type
    let adapterInput: Record<string, unknown>;
    if (adapter === "ecommerce_product") {
      adapterInput = { product_image_path: inputValue.trim() };
    } else if (adapter === "blog_article") {
      adapterInput = { url: inputValue.trim() };
    } else if (adapter === "storyboard_manual") {
      try {
        adapterInput = JSON.parse(inputValue.trim()) as Record<string, unknown>;
      } catch {
        setFieldErrors((prev) => ({ ...prev, input: "JSON không hợp lệ." }));
        return;
      }
    } else {
      adapterInput = { script: inputValue.trim() };
    }

    setSubmitting(true);
    try {
      const { data } = await apiClient.post<{ short_id: string; status: string }>(
        "/projects",
        {
          title: title.trim(),
          adapter_name: adapter,
          adapter_input: adapterInput,
          skill_id: skillId,
          aspect_ratio: aspectRatio,
          voice_id: voiceId || undefined,
        }
      );
      navigate(`/timeline/${data.short_id}`);
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : "Không tạo được dự án. Server đã chạy chưa?";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  // ─── Render ──────────────────────────────────────────────────────────────────

  const adapterMeta = ADAPTERS[adapter];

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link to="/" className="text-sm text-blue-600 hover:underline">
          ← Về trang chủ
        </Link>
        <h1 className="text-2xl font-bold mt-2">Dự án mới</h1>
        <p className="text-gray-500 text-sm mt-1">
          Chọn loại đầu vào, điền thông tin, rồi tạo video của bạn.
        </p>
      </div>

      <form onSubmit={handleSubmit} noValidate className="space-y-6">
        {/* Project title */}
        <div>
          <label htmlFor="title" className="block text-sm font-medium text-gray-700 mb-1">
            Tên dự án <span aria-hidden="true" className="text-red-500">*</span>
          </label>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Video sản phẩm của tôi"
            aria-required="true"
            aria-describedby={fieldErrors.title ? "title-error" : undefined}
            className={`w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              fieldErrors.title ? "border-red-400" : "border-gray-300"
            }`}
          />
          {fieldErrors.title && (
            <p id="title-error" role="alert" className="mt-1 text-xs text-red-600">
              {fieldErrors.title}
            </p>
          )}
        </div>

        {/* Adapter selector */}
        <fieldset>
          <legend className="block text-sm font-medium text-gray-700 mb-2">
            Loại đầu vào <span aria-hidden="true" className="text-red-500">*</span>
          </legend>
          <div className="grid grid-cols-2 gap-2">
            {(Object.entries(ADAPTERS) as [AdapterName, AdapterMeta][]).map(
              ([key, meta]) => (
                <label
                  key={key}
                  className={`flex flex-col gap-1 border rounded p-3 cursor-pointer transition-colors ${
                    adapter === key
                      ? "border-blue-500 bg-blue-50"
                      : "border-gray-200 hover:border-gray-400"
                  }`}
                >
                  <input
                    type="radio"
                    name="adapter"
                    value={key}
                    checked={adapter === key}
                    onChange={() => setAdapter(key)}
                    className="sr-only"
                  />
                  <span className="text-sm font-medium">{meta.label}</span>
                  <span className="text-xs text-gray-500">{meta.description}</span>
                </label>
              )
            )}
          </div>
        </fieldset>

        {/* Dynamic input field */}
        <div>
          <label htmlFor="adapter-input" className="block text-sm font-medium text-gray-700 mb-1">
            {adapterMeta.inputLabel}{" "}
            <span aria-hidden="true" className="text-red-500">*</span>
          </label>
          {adapterMeta.inputType === "textarea" || adapterMeta.inputType === "json" ? (
            <textarea
              id="adapter-input"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={adapterMeta.inputPlaceholder}
              rows={6}
              aria-required="true"
              aria-describedby={fieldErrors.input ? "input-error" : undefined}
              className={`w-full border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y ${
                fieldErrors.input ? "border-red-400" : "border-gray-300"
              }`}
            />
          ) : (
            <input
              id="adapter-input"
              type={adapterMeta.inputType === "url" ? "url" : "text"}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={adapterMeta.inputPlaceholder}
              aria-required="true"
              aria-describedby={fieldErrors.input ? "input-error" : undefined}
              className={`w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                fieldErrors.input ? "border-red-400" : "border-gray-300"
              }`}
            />
          )}
          {fieldErrors.input && (
            <p id="input-error" role="alert" className="mt-1 text-xs text-red-600">
              {fieldErrors.input}
            </p>
          )}
        </div>

        {/* Skill picker */}
        <div>
          <label htmlFor="skill" className="block text-sm font-medium text-gray-700 mb-1">
            Skill <span aria-hidden="true" className="text-red-500">*</span>
          </label>          <select
            id="skill"
            value={skillId}
            onChange={(e) => setSkillId(e.target.value)}
            aria-describedby={fieldErrors.skill ? "skill-error" : undefined}
            className={`w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white ${
              fieldErrors.skill ? "border-red-400" : "border-gray-300"
            }`}
          >
            {SKILLS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          {fieldErrors.skill && (
            <p id="skill-error" role="alert" className="mt-1 text-xs text-red-600">
              {fieldErrors.skill}
            </p>
          )}
        </div>

        {/* Voice picker */}
        <div>
          <label htmlFor="voice" className="block text-sm font-medium text-gray-700 mb-1">
            Giọng nói (TTS)
          </label>
          {voicesLoading ? (
            <p className="text-sm text-gray-400">Đang tải giọng nói…</p>
          ) : (
            <select
              id="voice"
              value={voiceId}
              onChange={(e) => setVoiceId(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
            >
              <option value="">— Dùng mặc định của skill —</option>
              {voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} ({v.language}, {v.gender})
                  {v.is_custom ? " ★ tùy chỉnh" : ""}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Aspect ratio */}
        <fieldset>
          <legend className="block text-sm font-medium text-gray-700 mb-2">
            Tỉ lệ khung hình
          </legend>
          <div className="flex gap-3">
            {(["9:16", "16:9", "1:1"] as const).map((ratio) => (
              <label
                key={ratio}
                className={`flex items-center gap-2 border rounded px-3 py-2 cursor-pointer text-sm transition-colors ${
                  aspectRatio === ratio
                    ? "border-blue-500 bg-blue-50 font-medium"
                    : "border-gray-200 hover:border-gray-400"
                }`}
              >
                <input
                  type="radio"
                  name="aspect"
                  value={ratio}
                  checked={aspectRatio === ratio}
                  onChange={() => setAspectRatio(ratio)}
                  className="sr-only"
                />
                {ratio}
              </label>
            ))}
          </div>
        </fieldset>

        {/* Global error */}
        {error && (
          <div role="alert" className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Submit */}
        <div className="flex items-center gap-4 pt-2">
          <button
            type="submit"
            disabled={submitting}
            className="px-6 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            {submitting ? "Đang tạo…" : "Tạo dự án"}
          </button>
          <Link to="/" className="text-sm text-gray-500 hover:underline">
            Hủy
          </Link>
        </div>
      </form>
    </div>
  );
}
