import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { btnGhost, btnPrimary, card, fieldLabel, input } from "../components/ui";
import ScriptQuality, { editorialChecks, type QualityReport } from "../components/ScriptQuality";
import ScriptSceneEditor, { type EditableScene } from "../components/ScriptSceneEditor";
import ScriptEditorialContent from "../components/ScriptEditorialContent";

type Step = "outline" | "script" | "review" | "revise";
type Revision = {
  id: number; parent_id: number | null; title: string; stage: string; status: string;
  content: Record<string, unknown>; provider: string; model: string;
  usage: Record<string, unknown> | null; error: string; approved: boolean;
  project_id: number | null; created_at: string;
  project_aspect?: string | null;
  quality?: QualityReport; editorially_approved?: boolean; can_revise?: boolean;
  latest_review?: Revision | null;
  approval?: { notes: string; created_at: string } | null;
  brief?: Record<string, unknown> | null;
};
type Model = { id: string; name: string };
type Series = { id: number; name: string; version: number; bible: string; language: string };
type Connection = { configured: boolean; codex_reason: string; codex_enabled: boolean; gemini_enabled: boolean };
type ScriptScene = EditableScene;
const labels: Record<string, string> = {
  brief: "Brief", outline: "Dàn ý", script: "Kịch bản", review: "Nhận xét",
  revise: "Bản AI sửa", manual: "Bản nhập / sửa tay",
};
const statuses: Record<string, string> = {
  succeeded: "Hoàn tất", pending: "Chờ xử lý", running: "Đang xử lý", failed: "Lỗi",
  waiting_user: "Chờ bạn xử lý", interrupted: "Cần kết nối lại", cancelled: "Đã dừng", timed_out: "Hết thời gian",
};
const nextStep: Record<string, Step> = {
  brief: "outline", outline: "script", script: "review", manual: "review", revise: "review", review: "revise",
};
const example = {
  title: "The missing key",
  scenes: [{ visual_prompt: "An empty hallway, a brass key on a dark wooden table, cold cinematic light.",
    narration: "The key appeared every night. This time, someone was waiting.", duration: 8, location_hint: "indoor" }],
  continuity_notes: "Keep the brass key and hallway identical across shots.",
};
const emptyScript = {
  title: "", continuity_notes: "", scenes: [{ visual_prompt: "", narration: "", duration: 8,
    location_hint: "unspecified", story_beat: "unspecified", purpose: "" }],
};

async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/scripts${path}`, {
    method, headers: { "Content-Type": "application/json", "X-AIFlow-Client": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data));
  return data as T;
}

async function loadRevisions(selected: number | null): Promise<Revision[]> {
  const [summaries, detail] = await Promise.all([
    api<Revision[]>(""), selected ? api<Revision>(`/${selected}`) : Promise.resolve(null),
  ]);
  if (!detail) return summaries;
  return summaries.some((item) => item.id === detail.id)
    ? summaries.map((item) => item.id === detail.id ? detail : item)
    : [detail, ...summaries];
}

function download(name: string, content: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ScriptStudio() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const selected = Number(params.get("revision")) || null;
  const [rows, setRows] = useState<Revision[]>([]);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [key, setKey] = useState("");
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState("");
  const [textProvider, setTextProvider] = useState("openrouter");
  const [geminiModel, setGeminiModel] = useState("");
  const [series, setSeries] = useState<Series[]>([]);
  const [seriesId, setSeriesId] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [title, setTitle] = useState("");
  const [idea, setIdea] = useState("");
  const [bible, setBible] = useState("");
  const [briefLanguage, setBriefLanguage] = useState("en");
  const [entryMode, setEntryMode] = useState<"ai" | "manual">("ai");
  const [manualLanguage, setManualLanguage] = useState("vi");
  const [seconds, setSeconds] = useState(240);
  const [audience, setAudience] = useState("Adults who enjoy original short mysteries");
  const [tone, setTone] = useState("Suspenseful, grounded, non-graphic");
  const [promise, setPromise] = useState("");
  const [constraints, setConstraints] = useState("");
  const [wpm, setWpm] = useState(135);
  const [editor, setEditor] = useState(JSON.stringify(example, null, 2));
  const [importStage, setImportStage] = useState<Step | "manual">("manual");
  const [aspect, setAspect] = useState("16:9");
  const [checks, setChecks] = useState<string[]>([]);
  const [ackWarnings, setAckWarnings] = useState(false);
  const [approvalNotes, setApprovalNotes] = useState("");
  const [refreshTick, setRefreshTick] = useState(0);
  const [codexModel, setCodexModel] = useState("default");
  const row = rows.find((item) => item.id === selected && (item.status !== "succeeded" || Object.keys(item.content).length > 0));
  const isScript = row && ["script", "revise", "manual"].includes(row.stage) && row.status === "succeeded";
  const step = row && !(row.stage === "review" && row.can_revise === false) ? nextStep[row.stage] : undefined;
  const scriptScenes = isScript ? row.content.scenes as ScriptScene[] : [];
  const entirelySilent = scriptScenes.length > 0 && scriptScenes.every(scene => !scene.narration.trim());
  async function loadSeries(): Promise<Series[]> {
    const response = await fetch("/api/studio/series", { headers: { "X-AIFlow-Client": "1" } });
    if (!response.ok) throw new Error("Không tải được series. Kiểm tra kết nối rồi bấm Tải lại series.");
    return response.json();
  }
  useEffect(() => {
    let active = true;
    loadSeries().then(value => { if (active) setSeries(value); }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    let polling = false;
    setLoading(true);
    async function poll() {
      if (polling) return;
      polling = true;
      try {
        const [revisions, state] = await Promise.all([loadRevisions(selected), api<Connection>("/connection")]);
        if (active) { setRows(revisions); setConnection(state); }
        const current = revisions.find(r => r.id === selected);
        if (active && current?.provider === "codex_cli" && current.usage?.transport === "cao-tmux" && ["pending", "running", "waiting_user", "interrupted"].includes(current.status)) {
          const synced = await api<Revision>(`/${selected}/codex/sync`, "POST");
          if (active && synced.status !== current.status) setRefreshTick(value => value + 1);
        }
      } catch (err) { if (active) setError(String(err)); }
      finally { polling = false; if (active) setLoading(false); }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [selected, refreshTick]);
  useEffect(() => { setChecks([]); setAckWarnings(false); setApprovalNotes(""); setImportStage("manual"); }, [selected]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); setRefreshTick((value) => value + 1); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }
  async function selectResult(result: Revision) {
    setRows((current) => [result, ...current.filter((item) => item.id !== result.id)]);
    setParams({ revision: String(result.id) });
    if (result.error) setError(result.error);
  }

  return <main className="mx-auto max-w-7xl px-4 py-8 sm:px-8">
    <nav className="mb-6 flex flex-wrap gap-4 text-sm text-emerald-400" aria-label="Điều hướng">
      <Link to="/">← Trang chủ</Link><Link to="/projects">Dự án</Link><Link to="/connections">Colab & giọng đọc</Link>
    </nav>
    <header className="mb-6"><p className="text-sm text-emerald-400">Xưởng nội dung · Fiction / series</p>
      <h1 className="mt-1 text-3xl font-semibold">Kịch bản & phiên bản</h1>
      <p className="mt-2 text-zinc-400">Tạo kịch bản bằng AI hoặc nhập thủ công → kiểm tra → bạn duyệt → tạo dự án. Không cần bật Colab ở bước này.</p>
    </header>
    {error && <div role="alert" className="mb-4 rounded-xl border border-rose-400/30 p-4 text-rose-300 break-words">{error}</div>}
    <p role="status" aria-live="polite" className="mb-4 text-sm text-emerald-300">{busy ? "Đang xử lý… Có thể mất khoảng 2 phút. Không cần bấm lại." : notice}</p>
    <details className={`${card} mb-6 p-5`}>
      <summary className="cursor-pointer font-medium">Nguồn AI · OpenRouter {connection?.configured ? "đã nhập key" : "chưa nhập key"} · chỉ miễn phí</summary>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div><label className={fieldLabel} htmlFor="text-key">OpenRouter API key (chỉ giữ trong bộ nhớ server)</label>
          <input id="text-key" className={`${input} mt-2`} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
          <div className="mt-3 flex flex-wrap gap-2">
            <button className={btnPrimary} disabled={busy || !key.trim()} onClick={() => void act(async () => {
              await api("/connection", "PUT", { key }); setKey(""); setNotice("Đã giữ key cho phiên server này. Chưa gọi AI.");
            })}>Lưu key cho phiên này</button>
            <button className={btnGhost} disabled={busy || !connection?.configured} onClick={() => void act(async () => {
              await api("/connection", "PUT", { key: "" }); setNotice("Đã xóa key khỏi bộ nhớ server.");
            })}>Ngắt kết nối</button>
          </div>
        </div>
        <div><p className="text-sm text-zinc-400">Danh sách được lọc theo giá 0 và hỗ trợ JSON schema. Mỗi lần sinh đều kiểm tra lại giá; hết quota sẽ dừng.</p>
          <button className={`${btnGhost} mt-3`} disabled={busy} onClick={() => void act(async () => {
            const available = await api<Model[]>("/models"); setModels(available);
            setModel(available.some((item) => item.id === model) ? model : available[0]?.id ?? "");
            setNotice(available.length ? "Đã tải danh sách. Chưa gửi nội dung tới AI." : "Chưa có model đáp ứng điều kiện; có thể nhập JSON thủ công.");
          })}>Tải model miễn phí</button>
          <p className="mt-4 text-sm text-amber-200">Codex/tmux: {connection?.codex_reason} <Link className="underline" to="/studio-settings">Cấu hình WSL/CAO</Link></p>
        </div>
      </div>
    </details>
    <div className="grid items-start gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className={`${card} p-4`}>
        <div className="flex items-center justify-between"><h2 className="font-semibold">Lịch sử</h2>
          <button className={btnGhost} disabled={busy} onClick={() => setParams({})}>Kịch bản mới</button></div>
        <p className="my-3 text-xs text-zinc-500">300 checkpoint gần nhất · bản cũ được giữ trong database</p>
        {loading && <p role="status">Đang tải…</p>}
        {!loading && !rows.length && <p className="text-sm text-zinc-400">Chưa có kịch bản. Chọn cách nhập bên cạnh.</p>}
        <ul className="max-h-[65vh] space-y-2 overflow-y-auto">{rows.map((item) => <li key={item.id}>
          <button disabled={busy} onClick={() => setParams({ revision: String(item.id) })} aria-current={item.id === selected ? "true" : undefined}
            className={`w-full rounded-xl border p-3 text-left text-sm focus-visible:ring-2 focus-visible:ring-emerald-400 ${item.id === selected ? "border-emerald-500/50 bg-emerald-500/10" : "border-white/10"}`}>
            <span className="block font-medium">#{item.id} · {item.title}</span>
            <span className="mt-1 block text-xs text-zinc-400">{labels[item.stage]} · {item.approved ? "Đã duyệt" : statuses[item.status]}</span>
          </button>
        </li>)}</ul>
      </aside>
      <section className={`${card} min-w-0 p-5 sm:p-6`}>
        {!selected ? <>
          <fieldset className="mb-5 space-y-3" disabled={busy}>
            <legend className={fieldLabel}>Cách tạo kịch bản</legend>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2"><input type="radio" name="entry-mode" checked={entryMode === "ai"} onChange={() => setEntryMode("ai")} />AI từ brief</label>
              <label className="flex items-center gap-2"><input type="radio" name="entry-mode" checked={entryMode === "manual"} onChange={() => setEntryMode("manual")} />Nhập kịch bản thủ công</label>
            </div>
          </fieldset>
          {entryMode === "manual" ? <div className="space-y-5">
            <h2 className="text-xl font-semibold">Kịch bản thủ công</h2>
            <p className="text-sm text-zinc-400">Lưu trực tiếp nội dung bạn nhập, không gọi AI viết kịch bản. Mỗi cảnh 4–8 giây, tổng tối đa 360 giây.</p>
            <label className={fieldLabel}>Ngôn ngữ lời dẫn<select className={`${input} mt-2`} disabled={busy} value={manualLanguage} onChange={e => setManualLanguage(e.target.value)}><option value="vi">Tiếng Việt</option><option value="en">Tiếng Anh</option></select></label>
            <label className={fieldLabel}>Nhịp đọc dự kiến ({manualLanguage === "vi" ? "tiếng/phút" : "từ/phút"})<input type="number" className={`${input} mt-2`} disabled={busy} min={100} max={manualLanguage === "vi" ? 300 : 180} value={wpm} onChange={e => setWpm(Number(e.target.value))} /></label>
            <p className="text-xs text-zinc-400">{manualLanguage === "vi" ? "Đếm tiếng tách bằng khoảng trắng; có thể nhập 240 tiếng/phút rồi đo lại bằng giọng TTS đã chọn." : "Đếm từ tiếng Anh, giới hạn 100–180 từ/phút."} Đây là ước tính kịch bản, không đổi tốc độ giọng TTS.</p>
            <ScriptSceneEditor content={emptyScript} busy={busy} creating onSave={async content => {
              let saved = false;
              await act(async () => {
                await selectResult(await api<Revision>("/manual", "POST", { request_id: crypto.randomUUID(), content, language: manualLanguage, narration_wpm: wpm }));
                saved = true; setNotice("Đã lưu kịch bản thủ công. Kiểm tra và duyệt để tạo dự án.");
              });
              return saved;
            }} />
          </div> : <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); void act(async () => {
          await selectResult(await api<Revision>("/brief", "POST", { request_id: crypto.randomUUID(),
            series_id: seriesId ? Number(seriesId) : null, series_version: series.find(s => s.id === Number(seriesId))?.version,
            content: { title, idea, series_bible: bible, language: briefLanguage, target_seconds: seconds, audience, tone,
              viewer_promise: promise, constraints, narration_wpm: wpm } }));
        }); }}>
          <h2 className="text-xl font-semibold">Bắt đầu tập mới</h2>
          <label className={fieldLabel}>Ngôn ngữ (tập có series kế thừa cấu hình series)<select className={input} disabled={!!seriesId} value={briefLanguage} onChange={e => setBriefLanguage(e.target.value)}><option value="en">Tiếng Anh</option><option value="vi">Tiếng Việt</option></select></label>
          <label className={fieldLabel}>Series<select className={`${input} mt-2`} value={seriesId} onChange={e => { setSeriesId(e.target.value); const s = series.find(x => x.id === Number(e.target.value)); if (s) { setBible(s.bible); setBriefLanguage(s.language); } }}><option value="">Tập độc lập</option>{series.map(s => <option key={s.id} value={s.id}>{s.name} · v{s.version}</option>)}</select></label>
          <button type="button" className={btnGhost} disabled={busy} onClick={() => void act(async () => {
            const fresh = await loadSeries(); setSeries(fresh);
            const current = fresh.find(item => item.id === Number(seriesId));
            if (current) { setBible(current.bible); setBriefLanguage(current.language); }
            else if (seriesId) setSeriesId("");
            setNotice("Đã tải lại series; brief đang nhập được giữ.");
          })}>Tải lại series</button>
          <Link className="text-sm text-emerald-300" to="/studio-settings">Quản lý series, nhân vật và kết nối</Link>
          <label className={fieldLabel}>Tên tập<input className={`${input} mt-2`} required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <label className={fieldLabel}>Ý tưởng & khán giả<textarea className={`${input} mt-2`} required rows={5} maxLength={10000} value={idea} onChange={(e) => setIdea(e.target.value)} /></label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className={fieldLabel}>Khán giả cụ thể<input className={`${input} mt-2`} maxLength={1000} value={audience} onChange={(e) => setAudience(e.target.value)} /></label>
            <label className={fieldLabel}>Giọng điệu<input className={`${input} mt-2`} maxLength={1000} value={tone} onChange={(e) => setTone(e.target.value)} /></label>
          </div>
          <label className={fieldLabel}>Lời hứa với người xem / câu hỏi sẽ được trả lời<textarea className={`${input} mt-2`} rows={2} maxLength={2000} value={promise} onChange={(e) => setPromise(e.target.value)} placeholder="Ví dụ: Vì sao chiếc chìa khóa luôn trở lại, dù nhân vật đã ném nó xuống sông?" /></label>
          <label className={fieldLabel}>Bắt buộc giữ / cần tránh<textarea className={`${input} mt-2`} rows={2} maxLength={3000} value={constraints} onChange={(e) => setConstraints(e.target.value)} /></label>
          <label className={fieldLabel}>Bối cảnh series, nhân vật & quy tắc cần giữ<textarea className={`${input} mt-2`} rows={5} maxLength={20000} readOnly={!!seriesId} value={bible} onChange={(e) => setBible(e.target.value)} /></label>
          <label className={fieldLabel}>Thời lượng mục tiêu (giây)<input type="number" className={`${input} mt-2`} min={30} max={360} required value={seconds} onChange={(e) => setSeconds(Number(e.target.value))} /></label>
          <label className={fieldLabel}>Nhịp đọc dự kiến ({briefLanguage === "vi" ? "tiếng/phút" : "từ/phút"})<input type="number" className={`${input} mt-2`} min={100} max={briefLanguage === "vi" ? 300 : 180} required value={wpm} onChange={(e) => setWpm(Number(e.target.value))} /></label>
          <p className="text-xs text-zinc-400">{briefLanguage === "vi" ? "Đếm tiếng tách bằng khoảng trắng; có thể nhập 240 tiếng/phút rồi đo lại bằng giọng TTS đã chọn." : "135 từ/phút là giả định biên tập ban đầu."} Đây là ước tính kịch bản, không đổi tốc độ giọng TTS. Không cần lấp đầy mọi giây bằng lời nói.</p>
          <button className={btnPrimary} disabled={busy}>Lưu brief</button>
        </form>}
        </> : !row ? <p role="status">{loading ? "Đang tải phiên bản…" : "Chưa tải được phiên bản. Kiểm tra kết nối hoặc chọn lại từ lịch sử."}</p> : <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><p className="text-sm text-emerald-400">#{row.id} · {labels[row.stage]} · {row.approved ? "Đã duyệt" : statuses[row.status]}</p>
              <h2 className="mt-1 text-xl font-semibold">{row.title}</h2>
              {row.parent_id && <button className="mt-2 text-sm text-emerald-400" disabled={busy} onClick={() => setParams({ revision: String(row.parent_id) })}>← Checkpoint trước #{row.parent_id}</button>}
            </div>
            <button className={btnGhost} onClick={() => download(`script-${row.id}.json`, JSON.stringify(row.content, null, 2))} disabled={row.status !== "succeeded"}>Tải nội dung JSON</button>
          </div>
          <p className="mt-3 text-xs text-zinc-400">Nguồn: {row.provider} · Model: {row.model || "không áp dụng / nhập thủ công"} · Usage: {row.usage ? JSON.stringify(row.usage) : "chưa có số liệu"}</p>
          {row.brief && <button className={`${btnGhost} mt-3`} disabled={busy} onClick={() => {
            const source = row.brief!;
            setBriefLanguage(String(source.language ?? "en")); setSeriesId("");
            setTitle(String(source.title ?? "")); setIdea(String(source.idea ?? "")); setBible(String(source.series_bible ?? ""));
            setSeconds(Number(source.target_seconds ?? 240)); setAudience(String(source.audience ?? "Adults who enjoy original short mysteries"));
            setTone(String(source.tone ?? "Suspenseful, grounded, non-graphic")); setPromise(String(source.viewer_promise ?? ""));
            setConstraints(String(source.constraints ?? "")); setWpm(Number(source.narration_wpm ?? 135)); setEntryMode("ai"); setParams({});
            setNotice("Đã chép brief để chỉnh hoặc tạo tập mới. Chỉ tạo nhánh mới khi bấm Lưu brief.");
          }}>Chép brief để chỉnh / tạo tập mới</button>}
          {row.error && <p role="alert" className="mt-4 text-rose-300">{row.error}</p>}
          {row.provider === "codex_cli" && row.usage?.transport === "cao-tmux" && <div className="my-4 space-y-3 rounded-xl border border-white/10 p-4 text-sm">
            <p>Codex/tmux · {statuses[row.status]} · model yêu cầu: {row.model}</p>
            <p className="text-zinc-400">Kết nối lại sẽ đọc lượt hiện có, không tự gửi lại prompt. Dừng sẽ đóng riêng phiên tmux này.</p>
            <p className="text-xs text-zinc-400">Chạy trong terminal Ubuntu ({String(row.usage.distro)}):</p>
            <pre className="overflow-x-auto text-xs">{String(row.usage.attach_command || "Đồng bộ để lấy lệnh mở phiên tmux.")}</pre>
            {["pending", "running", "waiting_user", "interrupted"].includes(row.status) && <div className="flex flex-wrap gap-2">
              <button className={btnGhost} disabled={busy} onClick={() => void act(async () => { await selectResult(await api<Revision>(`/${row.id}/codex/sync`, "POST")); })}>Đồng bộ lượt hiện tại</button>
              <button className={btnGhost} disabled={busy} onClick={() => void act(async () => { await selectResult(await api<Revision>(`/${row.id}/codex/cancel`, "POST")); })}>Dừng Codex</button>
            </div>}
          </div>}
          {["running", "pending"].includes(row.status) && row.usage?.transport !== "cao-tmux" && <div className="mt-4 space-y-3 text-sm text-zinc-400">
            <p>Tác vụ được lưu trước khi gọi AI. Nếu server khởi động lại, hệ thống không tự gửi lại.</p>
            <button className={btnGhost} disabled={busy} onClick={() => void act(async () => {
              await api(`/${row.id}/abandon`, "POST");
            })}>Đánh dấu gián đoạn (sau 3 phút)</button>
          </div>}
          {row.status === "succeeded" && <>
            {row.quality && <ScriptQuality report={row.quality} />}
            {isScript ? <div className="my-5 space-y-4">
              <p className="text-sm text-zinc-400">{scriptScenes.length} cảnh · {scriptScenes.reduce((total, scene) => total + scene.duration, 0)} giây theo kịch bản (chưa đo audio thực tế)</p>
              <ol className="max-h-[36rem] space-y-3 overflow-auto">{scriptScenes.map((scene, index) => <li id={`script-scene-${index + 1}`} key={index} className="scroll-mt-4 rounded-xl border border-white/10 p-4">
                <h3 className="text-sm font-medium text-emerald-400">Cảnh {index + 1} · {scene.duration}s · {scene.location_hint}</h3>
                <p className="mt-2 whitespace-pre-wrap text-zinc-100">{scene.narration}</p>
                <p className="mt-3 whitespace-pre-wrap text-sm text-zinc-400">Hình ảnh: {scene.visual_prompt}</p>
                <p className="mt-2 text-xs text-zinc-400">{scene.story_beat ?? "unspecified"} · {scene.purpose || "Chưa ghi vai trò của cảnh"}</p>
                {row.quality?.scenes[index] && <p className="mt-2 text-xs text-zinc-500">Từ giây {row.quality.scenes[index].start} · {row.quality.scenes[index].words} {row.quality.narration_unit === "syllables" ? "tiếng" : "từ"} · lời đọc ước tính {row.quality.scenes[index].estimated_speech_seconds}s</p>}
              </li>)}</ol>
              <p className="whitespace-pre-wrap text-sm text-zinc-400">Ghi chú liên tục: {String(row.content.continuity_notes ?? "")}</p>
              <details><summary className="cursor-pointer text-sm text-zinc-400">Xem JSON gốc</summary><pre className="mt-3 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(row.content, null, 2)}</pre></details>
            </div> : <ScriptEditorialContent stage={row.stage} content={row.content} />}
            {isScript && <details className="my-5 border-t border-white/10 pt-5"><summary className="cursor-pointer font-medium">Sửa từng cảnh trực tiếp</summary>
              <ScriptSceneEditor key={row.id} busy={busy} content={{ title: String(row.content.title), scenes: scriptScenes, continuity_notes: String(row.content.continuity_notes ?? "") }} onSave={async (content) => {
                let saved = false;
                await act(async () => {
                  await selectResult(await api<Revision>("/import", "POST", { request_id: crypto.randomUUID(), parent_id: row.id, stage: "manual", content }));
                  saved = true; setNotice("Đã lưu bản sửa mới. Hãy xem kiểm tra trước sản xuất và duyệt lại.");
                });
                return saved;
              }} />
            </details>}
            {row.latest_review && <details className="my-5 rounded-xl border border-white/10 p-4" open>
              <summary className="cursor-pointer font-medium">Nhận xét AI gần nhất · #{row.latest_review.id}</summary>
              <p className="mt-2 text-sm text-zinc-300">{String(row.latest_review.content.summary ?? "")}</p>
              <button className={`${btnGhost} mt-3`} disabled={busy} onClick={() => setParams({ revision: String(row.latest_review!.id) })}>Đọc rubric / tạo bản sửa</button>
            </details>}
            {row.stage === "review" && !step && <p className="my-4 text-amber-200">Đã dùng một vòng AI sửa. Quay về kịch bản cha để sửa tay hoặc duyệt sau khi tự rà.</p>}
            {step && <div className="space-y-3 border-t border-white/10 pt-5">
              <label className={fieldLabel}>Nguồn tạo kịch bản<select className={input} value={textProvider} onChange={e => setTextProvider(e.target.value)}><option value="openrouter">OpenRouter free-only</option><option value="gemini">Gemini đã cấu hình quota/billing</option><option value="codex_cli">Codex · ChatGPT qua tmux</option></select></label>
              {textProvider === "codex_cli" && <div className="space-y-2"><label className={fieldLabel}>Model Codex<input className={input} value={codexModel} onChange={e => setCodexModel(e.target.value)} placeholder="default hoặc tên model trong tài khoản" /></label><p className="text-xs text-zinc-400">default dùng model cấu hình trong Codex WSL. Không tự chuyển model khi lỗi/quota. <Link className="underline" to="/studio-settings">Cấu hình kết nối</Link></p></div>}
              {textProvider === "gemini" && <label className={fieldLabel}>Model Gemini<input className={input} value={geminiModel} onChange={e => setGeminiModel(e.target.value)} placeholder="Nhập model hỗ trợ structured output" /></label>}
              {textProvider === "openrouter" && <><label className={fieldLabel} htmlFor="script-model">Model OpenRouter miễn phí</label>
              <select id="script-model" className={input} value={model} onChange={(e) => setModel(e.target.value)}>
                {!models.length && <option value="">Mở Nguồn AI → Tải model miễn phí</option>}
                {models.map((item) => <option className="bg-zinc-900" key={item.id} value={item.id}>{item.name} · {item.id}</option>)}
              </select></>}
              <div className="flex flex-wrap gap-2">
                <button className={btnPrimary} disabled={busy || (textProvider === "openrouter" ? !connection?.configured || !model : textProvider === "gemini" ? !connection?.gemini_enabled || !geminiModel : !connection?.codex_enabled || !codexModel.trim())} onClick={() => void act(async () => {
                  await selectResult(await api<Revision>("/step", "POST", { request_id: crypto.randomUUID(), parent_id: row.id, stage: step, model: textProvider === "gemini" ? geminiModel : textProvider === "codex_cli" ? codexModel : model, provider: textProvider }));
                })}>AI: {labels[step]}</button>
                <button className={btnGhost} disabled={busy} onClick={() => void act(async () => {
                  const result = await api<{ prompt: string }>(`/${row.id}/prompt/${step}`);
                  download(`prompt-${row.id}-${step}.txt`, result.prompt, "text/plain");
                  setImportStage(step); setNotice(`Đã tải prompt. Nhập JSON kết quả vào mục bên dưới với loại “${labels[step]}”.`);
                })}>Tải prompt để làm thủ công</button>
              </div>
              <p className="text-xs text-zinc-500">Mỗi nút gọi một bước. Tối đa một vòng AI sửa trong mỗi nhánh lịch sử.</p>
            </div>}
            <details className="mt-6 border-t border-white/10 pt-5">
              <summary className="cursor-pointer font-medium">Nhập kết quả AI / lưu bản sửa tay</summary>
              <p className="my-3 text-sm text-zinc-400">Dán JSON đúng schema trong prompt. Bản sửa luôn tạo checkpoint mới và cần duyệt lại. Ví dụ một cảnh chỉ để minh họa định dạng.</p>
              <label className={fieldLabel}>Loại nội dung<select className={`${input} my-2`} value={importStage} onChange={(e) => setImportStage(e.target.value as Step | "manual")}>
                <option className="bg-zinc-900" value="manual">Kịch bản sửa tay</option>
                {step && <option className="bg-zinc-900" value={step}>{labels[step]} từ prompt</option>}
              </select></label>
              <label className={fieldLabel}>Nội dung JSON<textarea className={`${input} mt-2 font-mono`} rows={14} maxLength={250000} value={editor} onChange={(e) => setEditor(e.target.value)} /></label>
              <div className="mt-3 flex flex-wrap gap-2">
                {isScript && <button className={btnGhost} disabled={busy} onClick={() => { setEditor(JSON.stringify(row.content, null, 2)); setImportStage("manual"); }}>Chép bản này vào ô sửa</button>}
                <button className={btnPrimary} disabled={busy || !editor.trim()} onClick={() => void act(async () => {
                  await selectResult(await api<Revision>("/import", "POST", { request_id: crypto.randomUUID(), parent_id: row.id, stage: importStage, content: JSON.parse(editor) }));
                  setNotice("Đã lưu bản mới; bản trước vẫn được giữ.");
                })}>Lưu phiên bản mới</button>
              </div>
            </details>
            {isScript && <div className="mt-6 space-y-4 border-t border-white/10 pt-5">
              <h3 className="font-semibold">Duyệt trước sản xuất</h3>
              {!row.editorially_approved ? <>
                {row.approved && <p className="text-sm text-amber-200">Bản này được duyệt theo luồng cũ; cần xác nhận checklist biên tập mới.</p>}
                {editorialChecks.map(([id, label]) => <label key={id} className="flex items-start gap-3 text-sm text-zinc-300"><input type="checkbox" className="mt-1" checked={checks.includes(id)} onChange={(e) => setChecks(e.target.checked ? [...checks, id] : checks.filter((value) => value !== id))} />{id === "read_aloud" && entirelySilent ? "Đã xác nhận toàn bộ cảnh chủ ý không có lời dẫn." : label}</label>)}
                {!!row.quality?.issues.some((item) => item.severity === "warning") && <label className="flex items-start gap-3 text-sm text-amber-200"><input type="checkbox" className="mt-1" checked={ackWarnings} onChange={(e) => setAckWarnings(e.target.checked)} />Đã đọc các cảnh báo; những điểm còn lại là lựa chọn biên tập có chủ ý.</label>}
                <label className={fieldLabel}>Ghi chú quyết định duyệt<textarea className={`${input} mt-2`} maxLength={3000} rows={2} value={approvalNotes} onChange={(e) => setApprovalNotes(e.target.value)} /></label>
                <button className={btnPrimary} disabled={busy || checks.length !== editorialChecks.length || !row.quality?.ready || (row.quality.issues.some((item) => item.severity === "warning") && !ackWarnings)} onClick={() => void act(async () => {
                  await api(`/${row.id}/approve`, "POST", { checklist: checks, acknowledge_warnings: ackWarnings, notes: approvalNotes });
                })}>Duyệt phiên bản #{row.id}</button>
              </> : <>
                <label className={fieldLabel}>Tỉ lệ khung hình<select className={`${input} mt-2`} disabled={!!row.project_id} value={row.project_aspect ?? aspect} onChange={(e) => setAspect(e.target.value)}>
                  <option className="bg-zinc-900">16:9</option><option className="bg-zinc-900">9:16</option><option className="bg-zinc-900">1:1</option>
                </select></label>
                <button className={btnPrimary} disabled={busy} onClick={() => void act(async () => {
                  const project = await api<{ id: number }>(`/${row.id}/project`, "POST", { aspect });
                  navigate(`/production?project=${project.id}`);
                })}>{row.project_id ? "Mở dự án đã tạo" : "Tạo dự án từ bản đã duyệt"}</button>
                <p className="text-xs text-zinc-400">Tạo cảnh và mở Xưởng sản xuất; chưa chạy TTS hay tạo video. Cấu hình giọng của series được giữ trong từng tập.</p>
              </>}
            </div>}
          </>}
        </>}
      </section>
    </div>
  </main>;
}
