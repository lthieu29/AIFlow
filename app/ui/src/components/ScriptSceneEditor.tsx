import { useState } from "react";
import { btnGhost, btnPrimary, fieldLabel, input } from "./ui";

export type EditableScene = {
  visual_prompt: string; narration: string; duration: number; location_hint: string;
  story_beat?: string; purpose?: string;
};
type ScriptContent = { title: string; scenes: EditableScene[]; continuity_notes: string };

export default function ScriptSceneEditor({ content, busy, onSave }: {
  content: ScriptContent; busy: boolean; onSave: (content: ScriptContent) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<ScriptContent>(() => structuredClone(content));
  const [error, setError] = useState("");
  const [activeScene, setActiveScene] = useState(0);
  const dirty = JSON.stringify(draft) !== JSON.stringify(content);
  function change(index: number, values: Partial<EditableScene>) {
    setDraft((current) => ({ ...current, scenes: current.scenes.map((scene, i) => i === index ? { ...scene, ...values } : scene) }));
  }
  function move(index: number, direction: number) {
    const scenes = [...draft.scenes];
    [scenes[index], scenes[index + direction]] = [scenes[index + direction], scenes[index]];
    setDraft({ ...draft, scenes });
    setActiveScene(index + direction);
  }
  return <form className="mt-4 space-y-4" onSubmit={(event) => {
    event.preventDefault(); setError("");
    const invalid = draft.scenes.findIndex((scene) => !scene.visual_prompt.trim() || !Number.isFinite(scene.duration) || scene.duration < 4 || scene.duration > 8);
    if (invalid >= 0) { setActiveScene(invalid); setError(`Cảnh ${invalid + 1} cần prompt hình ảnh và thời lượng 4–8 giây.`); return; }
    void onSave(draft).then((saved) => { if (!saved) setError("Chưa lưu được; phần chỉnh sửa vẫn ở đây."); });
  }}>
    <p className="text-sm text-zinc-400">Mỗi lần lưu tạo bản mới và cần duyệt lại. {dirty ? "Có thay đổi chưa lưu; hãy lưu trước khi rời trang." : "Đang sửa bản sao."}</p>
    {error && <p role="alert" className="text-rose-300">{error}</p>}
    <label className={fieldLabel}>Tên tập<input required maxLength={200} className={`${input} mt-2`} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
    <label className={fieldLabel}>Chọn cảnh để sửa<select className={`${input} mt-2`} value={activeScene} onChange={(e) => setActiveScene(Number(e.target.value))}>
      {draft.scenes.map((scene, index) => <option className="bg-zinc-900" key={index} value={index}>Cảnh {index + 1} · {scene.story_beat ?? "unspecified"} · {scene.duration}s</option>)}
    </select></label>
    {draft.scenes.map((scene, index) => index === activeScene && <fieldset className="space-y-3 rounded-xl border border-white/10 p-4" key={index} disabled={busy}>
      <legend className="px-2 text-emerald-400">Cảnh {index + 1}</legend>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className={fieldLabel}>Thời lượng (s)<input required type="number" min={4} max={8} step={0.1} className={`${input} mt-2`} value={scene.duration} onChange={(e) => change(index, { duration: Number(e.target.value) })} /></label>
        <label className={fieldLabel}>Vai trò<select className={`${input} mt-2`} value={scene.story_beat ?? "unspecified"} onChange={(e) => change(index, { story_beat: e.target.value })}>
          {["hook", "setup", "escalation", "reveal", "payoff", "unspecified"].map((value) => <option className="bg-zinc-900" key={value}>{value}</option>)}
        </select></label>
        <label className={fieldLabel}>Không gian<select className={`${input} mt-2`} value={scene.location_hint} onChange={(e) => change(index, { location_hint: e.target.value })}>
          {["indoor", "outdoor", "transition", "unspecified"].map((value) => <option className="bg-zinc-900" key={value}>{value}</option>)}
        </select></label>
      </div>
      <label className={fieldLabel}>Cảnh thay đổi điều gì?<input maxLength={1000} className={`${input} mt-2`} value={scene.purpose ?? ""} onChange={(e) => change(index, { purpose: e.target.value })} /></label>
      <label className={fieldLabel}>Lời dẫn (để trống nếu chủ ý không lời)<textarea maxLength={1000} rows={2} className={`${input} mt-2`} value={scene.narration} onChange={(e) => change(index, { narration: e.target.value })} /></label>
      <label className={fieldLabel}>Prompt hình ảnh<textarea required maxLength={3000} rows={3} className={`${input} mt-2`} value={scene.visual_prompt} onChange={(e) => change(index, { visual_prompt: e.target.value })} /></label>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={btnGhost} disabled={index === 0} onClick={() => move(index, -1)}>↑ Lên</button>
        <button type="button" className={btnGhost} disabled={index === draft.scenes.length - 1} onClick={() => move(index, 1)}>↓ Xuống</button>
        <button type="button" className={btnGhost} disabled={draft.scenes.length < 2} onClick={() => {
          setDraft({ ...draft, scenes: draft.scenes.filter((_, i) => i !== index) });
          setActiveScene(Math.min(index, draft.scenes.length - 2));
        }}>Bỏ cảnh khỏi bản sửa</button>
      </div>
    </fieldset>)}
    <button type="button" className={btnGhost} disabled={busy || draft.scenes.length >= 60} onClick={() => {
      setActiveScene(draft.scenes.length);
      setDraft({ ...draft, scenes: [...draft.scenes,
        { visual_prompt: "", narration: "", duration: 8, location_hint: "unspecified", story_beat: "unspecified", purpose: "" }] });
    }}>Thêm cảnh</button>
    <label className={fieldLabel}>Ghi chú liên tục<textarea maxLength={10000} rows={3} className={`${input} mt-2`} value={draft.continuity_notes} onChange={(e) => setDraft({ ...draft, continuity_notes: e.target.value })} /></label>
    <button className={btnPrimary} disabled={busy || !dirty}>Lưu bản sửa mới</button>
  </form>;
}
