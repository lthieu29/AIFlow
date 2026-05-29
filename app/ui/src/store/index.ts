/**
 * Zustand stores for AIFlow UI.
 *
 * useAppStore  — global app state (connection, selected voice, current project)
 * useVoiceStore — voice catalog with async fetch
 */

import { create } from "zustand";
import { getVoices } from "../api/client";
import type { VoiceInfo, Project } from "../api/client";

// ─── App store ────────────────────────────────────────────────────────────────

interface AppState {
  /** All available voices (preset + custom) */
  voices: VoiceInfo[];
  /** Currently selected voice ID */
  selectedVoice: string | null;
  /** Whether the Chrome extension is connected */
  isConnected: boolean;
  /** Currently open project */
  currentProject: Project | null;

  // Actions
  setVoices: (voices: VoiceInfo[]) => void;
  setSelectedVoice: (voiceId: string | null) => void;
  setConnected: (connected: boolean) => void;
  setCurrentProject: (project: Project | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  voices: [],
  selectedVoice: null,
  isConnected: false,
  currentProject: null,

  setVoices: (voices) => set({ voices }),
  setSelectedVoice: (voiceId) => set({ selectedVoice: voiceId }),
  setConnected: (connected) => set({ isConnected: connected }),
  setCurrentProject: (project) => set({ currentProject: project }),
}));

// ─── Voice store ──────────────────────────────────────────────────────────────

interface VoiceState {
  voices: VoiceInfo[];
  loading: boolean;
  error: string | null;

  /** Fetch voices from /api/tts/voices and update state */
  fetchVoices: () => Promise<void>;
}

export const useVoiceStore = create<VoiceState>((set) => ({
  voices: [],
  loading: false,
  error: null,

  fetchVoices: async () => {
    set({ loading: true, error: null });
    try {
      const voices = await getVoices();
      set({ voices, loading: false });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch voices";
      set({ error: message, loading: false });
    }
  },
}));
