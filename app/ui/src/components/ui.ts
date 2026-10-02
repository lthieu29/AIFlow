/**
 * Shared style tokens — dark theme, single emerald accent.
 *
 * Consistency locks:
 *  - Accent: emerald, used identically across the whole app.
 *  - Radius: inputs/buttons = rounded-xl, cards/panels = rounded-2xl, pills = rounded-full.
 *  - Focus: emerald ring with zinc-950 offset on every interactive element.
 *  - Contrast: emerald-500 bg + zinc-950 text (WCAG AA); zinc-100 body on zinc-950.
 */

const focus =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950";

const btnBase =
  `inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl px-4 py-2.5 text-sm font-medium transition-colors active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 ${focus}`;

export const btnPrimary = `${btnBase} bg-emerald-500 text-zinc-950 hover:bg-emerald-400`;

export const btnGhost = `${btnBase} border border-white/10 bg-white/[0.03] text-zinc-200 hover:bg-white/[0.06]`;

export const btnDanger = `${btnBase} border border-rose-500/30 bg-rose-500/5 text-rose-300 hover:bg-rose-500/15`;

const inputBase =
  `w-full rounded-xl border bg-white/[0.03] px-3.5 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 transition-colors disabled:opacity-40 ${focus}`;

export const input = `${inputBase} border-white/10`;

/** Input class with validation-aware border (avoids Tailwind border-color precedence issues). */
export const inputWith = (invalid: boolean) =>
  `${inputBase} ${invalid ? "border-rose-500/60" : "border-white/10"}`;

export const card = "rounded-2xl border border-white/10 bg-white/[0.02]";

export const fieldLabel = "block text-sm font-medium text-zinc-300";

export const link = `rounded text-sm text-emerald-400 hover:text-emerald-300 ${focus}`;
