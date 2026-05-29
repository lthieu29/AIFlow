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
    label: "E-commerce Product",
    description: "Generate a TikTok/Reels-style product video from an image path and metadata.",
    inputType: "text",
    inputLabel: "Product image path",
    inputPlaceholder: "storage/media/product.jpg",
  },
  narrative_script: {
    label: "Narrative Script",
    description: "Turn a markdown vlog/script into a video.",
    inputType: "textarea",
    inputLabel: "Markdown script",
    inputPlaceholder: "# My Story\n\nScene 1: ...",
  },
  blog_article: {
    label: "Blog Article",
    description: "Convert a blog URL or markdown into an explainer video.",
    inputType: "url",
    inputLabel: "Article URL",
    inputPlaceholder: "https://example.com/article",
  },
  storyboard_manual: {
    label: "Manual Storyboard",
    description: "Provide a JSON storyboard with scenes defined manually.",
    inputType: "json",
    inputLabel: "Storyboard JSON",
    inputPlaceholder: '{"scenes": [{"narration": "...", "visual_prompt": "..."}]}',
  },
};

const SKILLS = [
  { id: "ecommerce-fashion", label: "E-commerce Fashion" },
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
      errors.title = "Project title is required.";
    }

    if (!inputValue.trim()) {
      errors.input = `${ADAPTERS[adapter].inputLabel} is required.`;
    } else if (ADAPTERS[adapter].inputType === "url") {
      try {
        new URL(inputValue.trim());
      } catch {
        errors.input = "Please enter a valid URL.";
      }
    } else if (ADAPTERS[adapter].inputType === "json") {
      try {
        JSON.parse(inputValue.trim());
      } catch {
        errors.input = "Please enter valid JSON.";
      }
    }

    if (!skillId) {
      errors.skill = "Please select a skill.";
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
        setFieldErrors((prev) => ({ ...prev, input: "Invalid JSON." }));
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
          : "Failed to create project. Is the server running?";
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
          ← Back to home
        </Link>
        <h1 className="text-2xl font-bold mt-2">New Project</h1>
        <p className="text-gray-500 text-sm mt-1">
          Choose an input type, fill in the details, then generate your video.
        </p>
      </div>

      <form onSubmit={handleSubmit} noValidate className="space-y-6">
        {/* Project title */}
        <div>
          <label htmlFor="title" className="block text-sm font-medium text-gray-700 mb-1">
            Project title <span aria-hidden="true" className="text-red-500">*</span>
          </label>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="My product video"
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
            Input type <span aria-hidden="true" className="text-red-500">*</span>
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
          </label>
          <select
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
            TTS Voice
          </label>
          {voicesLoading ? (
            <p className="text-sm text-gray-400">Loading voices…</p>
          ) : (
            <select
              id="voice"
              value={voiceId}
              onChange={(e) => setVoiceId(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
            >
              <option value="">— Use skill default —</option>
              {voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} ({v.language}, {v.gender})
                  {v.is_custom ? " ★ custom" : ""}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Aspect ratio */}
        <fieldset>
          <legend className="block text-sm font-medium text-gray-700 mb-2">
            Aspect ratio
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
            {submitting ? "Creating…" : "Create project"}
          </button>
          <Link to="/" className="text-sm text-gray-500 hover:underline">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
