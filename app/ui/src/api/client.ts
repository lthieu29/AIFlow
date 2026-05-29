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
  const { data } = await apiClient.post<SynthesizeResponse>("/tts/synthesize", {
    text,
    voice,
    speed,
  });
  return data;
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
