/**
 * Axios API client for AIFlow backend.
 *
 * Base URL: /api  (proxied by Vite dev server to http://127.0.0.1:8101)
 */

import axios from "axios";

// ─── TypeScript interfaces matching server Pydantic models ────────────────────

/** Unified voice descriptor — mirrors server/audio/tts/voice_catalog.py VoiceInfo */
export interface VoiceInfo {
  id: string;
  name: string;
  backend: "vieneu" | "edge_tts" | string;
  language: string;
  gender: "male" | "female" | "neutral" | string;
  description: string;
  demo_audio_path: string | null;
  is_custom: boolean;
}

/** Response from POST /api/tts/synthesize */
export interface SynthesizeResponse {
  success: boolean;
  audio_path: string;
  duration_sec: number;
  backend: string;
}

/** Response from POST /api/tts/voices/custom */
export interface CustomVoiceUploadResponse {
  id: string;
  name: string;
  status: string;
}

/** Response from GET /api/health */
export interface HealthResponse {
  status: string;
  extension_connected: boolean;
  version: string;
  uptime_sec: number;
}

/** Project model (for future use in store) */
export interface Project {
  id: string;
  name: string;
  skill: string;
  status: string;
  created_at: string;
  updated_at: string;
}

// ─── Axios instance ───────────────────────────────────────────────────────────

export const apiClient = axios.create({
  baseURL: "/api",
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30_000,
});

// ─── API functions ────────────────────────────────────────────────────────────

/** GET /api/tts/voices — list all preset + custom voices */
export async function getVoices(): Promise<VoiceInfo[]> {
  const { data } = await apiClient.get<VoiceInfo[]>("/tts/voices");
  return data;
}

/**
 * POST /api/tts/synthesize — synthesize text to audio
 * @param text    Text to synthesize
 * @param voice   Voice ID (e.g. "Binh", "vi-VN-HoaiMyNeural")
 * @param speed   Playback speed multiplier (default 1.0)
 */
export async function synthesize(
  text: string,
  voice: string,
  speed = 1.0
): Promise<SynthesizeResponse> {
  type AudioTask = { id: number; status: string; error: string; audio_path: string; duration_sec: number };
  const selectedVoice = (await getVoices()).find(item => item.id === (voice || "af_heart"));
  if (!selectedVoice) throw new Error("Giọng không có trong worker đã lưu. Kiểm tra lại kết nối Colab.");
  const { data } = await apiClient.post<AudioTask>("/audio/tasks", {
    text, voice: selectedVoice.id, speed, language: selectedVoice.language, title: "Nghe thử giọng đọc",
  }, { headers: { "X-AIFlow-Client": "1" } });
  let task = data;
  const deadline = Date.now() + 15 * 60_000;
  while (["queued", "running"].includes(task.status) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 3000));
    task = (await apiClient.get<AudioTask>(`/audio/tasks/${task.id}`)).data;
  }
  if (task.status !== "succeeded") {
    throw new Error(task.error || "Tác vụ đã lưu. Mở Colab & giọng đọc để kết nối và tiếp tục.");
  }
  return { success: true, audio_path: task.audio_path, duration_sec: task.duration_sec, backend: "remote" };
}

/**
 * POST /api/tts/voices/custom — upload a custom voice package zip
 * @param file  Zip file produced by the Colab training notebook
 */
export async function uploadCustomVoice(
  file: File
): Promise<CustomVoiceUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<CustomVoiceUploadResponse>(
    "/tts/voices/custom",
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}

/**
 * GET /api/tts/voices/custom/{id} — get custom voice info by ID
 * @param id  Voice ID
 */
export async function getCustomVoice(id: string): Promise<VoiceInfo> {
  const { data } = await apiClient.get<VoiceInfo>(`/tts/voices/custom/${id}`);
  return data;
}

/**
 * DELETE /api/tts/voices/custom/{id} — delete a custom voice
 * @param id  Voice ID
 */
export async function deleteCustomVoice(id: string): Promise<{ deleted: boolean }> {
  const { data } = await apiClient.delete<{ deleted: boolean }>(
    `/tts/voices/custom/${id}`
  );
  return data;
}

/** GET /api/health — server liveness check */
export async function getHealth(): Promise<HealthResponse> {
  const { data } = await apiClient.get<HealthResponse>("/health");
  return data;
}

/** Skill metadata — mirrors server/api/routes/skills.py SkillInfo */
export interface SkillInfo {
  id: string;
  name: string;
  adapter_type: string;
  supported_adapters: string[];
  description: string | null;
}

/** GET /api/skills — list all available skills (data-only packs) */
export async function getSkills(): Promise<SkillInfo[]> {
  const { data } = await apiClient.get<SkillInfo[]>("/skills");
  return data;
}

// ─── Asset API ────────────────────────────────────────────────────────────────

/** Asset descriptor — mirrors server/db/models/asset.py */
export interface AssetInfo {
  id: number;
  project_id: number;
  name: string;
  type: "character" | "product" | "location" | "style";
  file_path: string | null;
  ref_url: string | null;
  source: string;
  created_at: string;
}

/**
 * POST /api/assets/upload — upload a reference image
 * @param file        Image file (jpg, png, webp)
 * @param projectId   Project this asset belongs to
 * @param name        Human-readable name
 * @param assetType   One of: character, product, location, style
 */
export async function uploadAsset(
  file: File,
  projectId: number,
  name: string,
  assetType: "character" | "product" | "location" | "style"
): Promise<AssetInfo> {
  const form = new FormData();
  form.append("file", file);
  form.append("project_id", String(projectId));
  form.append("name", name);
  form.append("type", assetType);
  const { data } = await apiClient.post<AssetInfo>("/assets/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/** GET /api/assets/{projectId} — list all assets for a project */
export async function getAssets(
  projectId: number
): Promise<{ assets: AssetInfo[]; count: number }> {
  const { data } = await apiClient.get<{ assets: AssetInfo[]; count: number }>(
    `/assets/${projectId}`
  );
  return data;
}

/** DELETE /api/assets/item/{assetId} — delete an asset */
export async function deleteAsset(assetId: number): Promise<{ deleted: boolean }> {
  const { data } = await apiClient.delete<{ deleted: boolean }>(
    `/assets/item/${assetId}`
  );
  return data;
}

/** Get asset image URL */
export function getAssetImageUrl(assetId: number): string {
  return `/api/assets/file/${assetId}`;
}

// ─── Content adapter API ─────────────────────────────────────────────────────

/** Per-scene preview row — mirrors server SceneSpecOut */
export interface SceneSpecOut {
  order: number;
  prompt: string;
  duration: number;
  location_hint: string | null;
  narration: string | null;
  start_image: string | null;
}

/** Cost breakdown returned by SceneList.estimate_cost() on the server. */
export interface SceneCostEstimate {
  scene_count: number;
  total_seconds: number;
  veo3_clips: number;
  estimated_credits?: number;
  [key: string]: unknown;
}

/** Response from POST /api/content/parse */
export interface SceneListOut {
  project_id: string;
  scenes: SceneSpecOut[];
  style_ref: string | null;
  voice: string | null;
  metadata: Record<string, unknown>;
  scene_count: number;
  estimated_cost: SceneCostEstimate;
}

/**
 * POST /api/content/parse — preview the scene list a ContentAdapter would
 * produce without persisting a project.  Used by NewProject's "Xem trước cảnh"
 * button so the user can review/edit before committing.
 */
export async function parseContent(
  adapter: string,
  inputData: Record<string, unknown>,
): Promise<SceneListOut> {
  const { data } = await apiClient.post<SceneListOut>("/content/parse", {
    adapter,
    input_data: inputData,
  });
  return data;
}

// ─── Project gates API ───────────────────────────────────────────────────────

/** Quality gate row — mirrors server QualityGate model fields used in UI. */
export interface QualityGateInfo {
  id: number;
  project_id: number;
  gate_id: string;
  status: string;
  message: string | null;
  created_at: string;
  updated_at: string;
}

/** GET /api/projects/{id}/gates/pending — gates currently in `checking`. */
export async function getPendingGates(
  projectId: string,
): Promise<QualityGateInfo[]> {
  const { data } = await apiClient.get<QualityGateInfo[]>(
    `/projects/${projectId}/gates/pending`,
  );
  return data;
}

/** POST /api/projects/{id}/gates/{gateId}/approve — mark gate as passed. */
export async function approveGate(
  projectId: string,
  gateId: number,
): Promise<QualityGateInfo> {
  const { data } = await apiClient.post<QualityGateInfo>(
    `/projects/${projectId}/gates/${gateId}/approve`,
  );
  return data;
}

/** POST /api/projects/{id}/gates/{gateId}/override — mark gate as overridden. */
export async function overrideGate(
  projectId: string,
  gateId: number,
): Promise<QualityGateInfo> {
  const { data } = await apiClient.post<QualityGateInfo>(
    `/projects/${projectId}/gates/${gateId}/override`,
  );
  return data;
}
