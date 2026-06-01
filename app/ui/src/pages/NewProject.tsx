/**
 * NewProject page — input adapter + skill picker + voice picker.
 *
 * Lets the user choose an adapter type, fill in the required input,
 * pick a skill and a TTS voice, then submit to POST /api/projects.
 */

import { useState, useEffect, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
  ArrowLeft,
  DeviceMobile,
  Monitor,
  Square,
  WarningCircle,
} from "@phosphor-icons/react";
import { apiClient, getSkills } from "../api/client";
import type { SkillInfo } from "../api/client";
import { useVoiceStore } from "../store";
import Combobox, { type ComboOption } from "../components/Combobox";
import { btnPrimary, inputWith, fieldLabel, link } from "../components/ui";

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

const ADAPTER_TYPE_BY_NAME: Record<AdapterName, string> = {
  ecommerce_product: "ecommerce_product",
  narrative_script: "narrative_script",
  blog_article: "blog_article",
  storyboard_manual: "storyboard_manual",
};

// Nhãn tiếng Việt cho skill (ID thư mục là khóa kỹ thuật, không đổi được).
const SKILL_LABELS_VI: Record<string, string> = {
  "ecommerce-beauty": "TMĐT — Mỹ phẩm",
  "ecommerce-fashion": "TMĐT — Thời trang",
  "ecommerce-food": "TMĐT — Ẩm thực",
  "ecommerce-home": "TMĐT — Đồ gia dụng",
  "ecommerce-jewelry": "TMĐT — Trang sức",
  "ecommerce-tech": "TMĐT — Công nghệ",
  "product-minimal-rotate": "Sản phẩm — Xoay tối giản",
  "product-tech-launch": "Sản phẩm — Ra mắt công nghệ",
  "cinematic-action": "Điện ảnh — Hành động",
  "cinematic-drama": "Điện ảnh — Chính kịch",
  "cinematic-noir": "Điện ảnh — Noir",
  "cinematic-romance": "Điện ảnh — Lãng mạn",
  "cinematic-thriller": "Điện ảnh — Giật gân",
  "cinematic-period": "Điện ảnh — Cổ trang",
  "explainer-tech": "Giải thích — Công nghệ",
  "explainer-finance": "Giải thích — Tài chính",
  "explainer-history": "Giải thích — Lịch sử",
  "kdrama-romance": "Phim Hàn — Lãng mạn",
  "action-extreme": "Hành động — Mạo hiểm",
  "action-sports-pov": "Hành động — Thể thao POV",
  "action-wuxia": "Hành động — Võ hiệp",
  "nature-landscape": "Thiên nhiên — Phong cảnh",
  "nature-wildlife": "Thiên nhiên — Động vật hoang dã",
  "nature-timelapse": "Thiên nhiên — Tua nhanh",
  "social-viral-hook": "Viral — Hook 3 giây",
  "social-viral-transform": "Viral — Biến hình",
  "social-viral-pet-comedy": "Viral — Thú cưng hài",
  "social-viral-meme": "Viral — Meme",
  "dialogue-interview": "Hội thoại — Phỏng vấn",
  "dialogue-vlog": "Hội thoại — Vlog",
  "dialogue-podcast-clip": "Hội thoại — Clip podcast",
  "travel-vlog": "Đời sống — Du lịch vlog",
  "lifestyle-wellness": "Đời sống — Sức khỏe",
  "experimental-abstract": "Thử nghiệm — Trừu tượng",
  "experimental-asmr": "Thử nghiệm — ASMR",
  "chinese-ink-wash": "Tranh thủy mặc Trung Hoa",
};

function skillLabel(id: string, fallback: string): string {
  return SKILL_LABELS_VI[id] ?? fallback ?? id;
}

function genderLabel(gender: string): string {
  if (gender === "male") return "Nam";
  if (gender === "female") return "Nữ";
  if (gender === "neutral") return "Trung tính";
  return gender;
}

const ASPECT_RATIOS = [
  { value: "9:16", label: "9:16", Icon: DeviceMobile },
  { value: "16:9", label: "16:9", Icon: Monitor },
  { value: "1:1", label: "1:1", Icon: Square },
] as const;

// ─── Component ────────────────────────────────────────────────────────────────

export default function NewProject() {
  const navigate = useNavigate();
  const { voices, loading: voicesLoading, fetchVoices } = useVoiceStore();

  const [title, setTitle] = useState("");
  const [adapter, setAdapter] = useState<AdapterName>("ecommerce_product");
  const [inputValue, setInputValue] = useState("");
  const [skillId, setSkillId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [aspectRatio, setAspectRatio] = useState<"9:16" | "16:9" | "1:1">("9:16");

  const [allSkills, setAllSkills] = useState<SkillInfo[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    fetchVoices();
  }, [fetchVoices]);

  useEffect(() => {
    setSkillsLoading(true);
    getSkills()
      .then(setAllSkills)
      .catch(() => setAllSkills([]))
      .finally(() => setSkillsLoading(false));
  }, []);

  const adapterType = ADAPTER_TYPE_BY_NAME[adapter];
  const compatibleSkills = allSkills.filter(
    (s) =>
      s.adapter_type === adapterType ||
      (s.supported_adapters ?? []).includes(adapterType)
  );

  useEffect(() => {
    if (voices.length > 0 && !voiceId) {
      const defaultVoice = voices.find((v) => v.id === "Binh") ?? voices[0];
      setVoiceId(defaultVoice.id);
    }
  }, [voices, voiceId]);

  useEffect(() => {
    setInputValue("");
    setFieldErrors({});
  }, [adapter]);

  useEffect(() => {
    if (compatibleSkills.length === 0) {
      setSkillId("");
      return;
    }
    if (!compatibleSkills.some((s) => s.id === skillId)) {
      setSkillId(compatibleSkills[0].id);
    }
  }, [compatibleSkills, skillId]);

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

  // ─── Combobox options ──────────────────────────────────────────────────────

  const adapterMeta = ADAPTERS[adapter];

  const skillOptions: ComboOption[] = compatibleSkills.map((s) => ({
    value: s.id,
    label: skillLabel(s.id, s.name),
  }));

  const voiceOptions: ComboOption[] = [
    { value: "", label: "Dùng mặc định của skill" },
    ...voices.map((v) => ({
      value: v.id,
      label: v.name + (v.is_custom ? " ★" : ""),
      hint: `${v.language}, ${genderLabel(v.gender)}`,
    })),
  ];

  const Required = () => (
    <span aria-hidden="true" className="text-emerald-400">
      *
    </span>
  );

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
      <Link to="/" className={link}>
        <span className="inline-flex items-center gap-1.5">
          <ArrowLeft size={16} />
          Về trang chủ
        </span>
      </Link>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight text-zinc-50">
        Dự án mới
      </h1>
      <p className="mt-1 text-sm text-zinc-400">
        Chọn loại đầu vào, điền thông tin, rồi tạo video của bạn.
      </p>

      <form onSubmit={handleSubmit} noValidate className="mt-8 space-y-7">
        {/* Project title */}
        <div className="space-y-2">
          <label htmlFor="title" className={fieldLabel}>
            Tên dự án <Required />
          </label>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Video sản phẩm của tôi"
            aria-required="true"
            aria-describedby={fieldErrors.title ? "title-error" : undefined}
            className={inputWith(Boolean(fieldErrors.title))}
          />
          {fieldErrors.title && (
            <p id="title-error" role="alert" className="flex items-center gap-1.5 text-xs text-rose-400">
              <WarningCircle size={14} weight="fill" />
              {fieldErrors.title}
            </p>
          )}
        </div>

        {/* Adapter selector */}
        <fieldset className="space-y-2">
          <legend className={fieldLabel}>
            Loại đầu vào <Required />
          </legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {(Object.entries(ADAPTERS) as [AdapterName, AdapterMeta][]).map(
              ([key, meta]) => {
                const checked = adapter === key;
                return (
                  <label
                    key={key}
                    className={`flex cursor-pointer flex-col gap-1 rounded-xl border p-3.5 transition-colors ${
                      checked
                        ? "border-emerald-500/50 bg-emerald-500/10"
                        : "border-white/10 bg-white/[0.02] hover:border-white/20"
                    }`}
                  >
                    <input
                      type="radio"
                      name="adapter"
                      value={key}
                      checked={checked}
                      onChange={() => setAdapter(key)}
                      className="sr-only"
                    />
                    <span
                      className={`text-sm font-medium ${
                        checked ? "text-emerald-100" : "text-zinc-200"
                      }`}
                    >
                      {meta.label}
                    </span>
                    <span className="text-xs leading-relaxed text-zinc-500">
                      {meta.description}
                    </span>
                  </label>
                );
              }
            )}
          </div>
        </fieldset>

        {/* Dynamic input field */}
        <div className="space-y-2">
          <label htmlFor="adapter-input" className={fieldLabel}>
            {adapterMeta.inputLabel} <Required />
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
              className={`${inputWith(Boolean(fieldErrors.input))} resize-y font-mono`}
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
              className={inputWith(Boolean(fieldErrors.input))}
            />
          )}
          {fieldErrors.input && (
            <p id="input-error" role="alert" className="flex items-center gap-1.5 text-xs text-rose-400">
              <WarningCircle size={14} weight="fill" />
              {fieldErrors.input}
            </p>
          )}
        </div>

        {/* Skill picker */}
        <div className="space-y-2">
          <label htmlFor="skill" className={fieldLabel}>
            Skill <Required />
          </label>
          <Combobox
            id="skill"
            value={skillId}
            onChange={setSkillId}
            options={skillOptions}
            disabled={skillsLoading || compatibleSkills.length === 0}
            invalid={Boolean(fieldErrors.skill)}
            placeholder={
              skillsLoading
                ? "Đang tải skill…"
                : compatibleSkills.length === 0
                ? "Không có skill phù hợp"
                : "Chọn skill"
            }
            ariaDescribedby={fieldErrors.skill ? "skill-error" : undefined}
          />
          {!skillsLoading && (
            <p className="text-xs text-zinc-500">
              {compatibleSkills.length} skill phù hợp với loại "{adapterMeta.label}"
            </p>
          )}
          {fieldErrors.skill && (
            <p id="skill-error" role="alert" className="flex items-center gap-1.5 text-xs text-rose-400">
              <WarningCircle size={14} weight="fill" />
              {fieldErrors.skill}
            </p>
          )}
        </div>

        {/* Voice picker */}
        <div className="space-y-2">
          <label htmlFor="voice" className={fieldLabel}>
            Giọng nói (TTS)
          </label>
          <Combobox
            id="voice"
            value={voiceId}
            onChange={setVoiceId}
            options={voiceOptions}
            disabled={voicesLoading}
            placeholder={voicesLoading ? "Đang tải giọng nói…" : "Chọn giọng nói"}
          />
        </div>

        {/* Aspect ratio */}
        <fieldset className="space-y-2">
          <legend className={fieldLabel}>Tỉ lệ khung hình</legend>
          <div className="inline-flex gap-1 rounded-xl border border-white/10 bg-white/[0.02] p-1">
            {ASPECT_RATIOS.map(({ value, label, Icon }) => {
              const checked = aspectRatio === value;
              return (
                <label
                  key={value}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg px-4 py-2 text-sm transition-colors ${
                    checked
                      ? "bg-emerald-500 font-medium text-zinc-950"
                      : "text-zinc-300 hover:bg-white/[0.06]"
                  }`}
                >
                  <input
                    type="radio"
                    name="aspect"
                    value={value}
                    checked={checked}
                    onChange={() => setAspectRatio(value)}
                    className="sr-only"
                  />
                  <Icon size={16} weight={checked ? "fill" : "regular"} />
                  {label}
                </label>
              );
            })}
          </div>
        </fieldset>

        {/* Global error */}
        {error && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
          >
            <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-rose-400" />
            {error}
          </div>
        )}

        {/* Submit */}
        <div className="flex items-center gap-4 pt-1">
          <button type="submit" disabled={submitting} className={btnPrimary}>
            {submitting ? "Đang tạo…" : "Tạo dự án"}
          </button>
          <Link to="/" className="text-sm text-zinc-500 hover:text-zinc-300">
            Hủy
          </Link>
        </div>
      </form>
    </div>
  );
}
