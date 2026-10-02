import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import axios from "axios";
import { ArrowLeft, ArrowSquareOut, CheckCircle, Plug, WarningCircle, Waveform } from "@phosphor-icons/react";
import { apiClient } from "../api/client";
import { btnGhost, btnPrimary, input as inputCls, card } from "../components/ui";

type Voice = { id: string; name: string; language: string; gender?: string; description?: string };
type Health = { engine?: string; model_revision?: string; runtime_id?: string; languages?: string[] };
type Connection = { url: string; configured: boolean; state: string; health: Health; voices: Voice[] };
type Checked = { fingerprint: string; health: Health; voices: Voice[] };
type Task = {
  id: number; title: string; status: string; voice: string; language: string;
  project_id: number | null; generation_job_id: number | null;
  completed_segments: number; total_segments: number; duration_sec: number;
  error: string; audio_url: string | null;
};
type Project = { id: number; name: string; short_id: string };
const local = { headers: { "X-AIFlow-Client": "1" } };
const labels: Record<string, string> = {
  waiting_resource: "Chờ kết nối / thao tác", queued: "Đang chờ xử lý", running: "Đang tạo audio",
  succeeded: "Đã lưu trên máy", needs_attention: "Cần xử lý", cancel_requested: "Đang yêu cầu hủy", cancelled: "Đã hủy",
  not_configured: "Chưa kết nối", ready: "Đã kết nối", unauthorized: "Token không hợp lệ",
  unreachable: "Mất kết nối", warming_up: "Đang nạp model", incompatible: "Cần kiểm tra cấu hình", busy: "Worker đang bận",
};

function errorText(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
    if (Array.isArray(detail)) return "Dữ liệu không hợp lệ. Kiểm tra các trường đã nhập.";
  }
  return "Không thực hiện được thao tác. Kiểm tra backend và thử lại.";
}

export default function AudioStudio() {
  const [params] = useSearchParams();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [checked, setChecked] = useState<Checked | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [text, setText] = useState("");
  const [project, setProject] = useState(params.get("project") ?? "");
  const [voice, setVoice] = useState("af_heart");
  const [projectLanguage, setProjectLanguage] = useState("en");
  const [loadingVoice, setLoadingVoice] = useState(!!project);
  const [voiceLoadFailed, setVoiceLoadFailed] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [profile, setProfile] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [loadedUrl, setLoadedUrl] = useState(false);
  const version = useRef(0);
  const live = useRef(true);

  const refresh = useCallback(async () => {
    const [c, t] = await Promise.all([apiClient.get<Connection>("/connections/audio"), apiClient.get<Task[]>("/audio/tasks")]);
    if (!live.current) return;
    setConnection(c.data);
    setTasks(t.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    live.current = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { await refresh(); } catch (err) { if (live.current) { setError(errorText(err)); setLoading(false); } }
      if (live.current) timer = setTimeout(poll, 4000);
    }
    void poll();
    void apiClient.get<Project[]>("/projects").then(({ data }) => { if (live.current) setProjects(data); }).catch(() => {});
    return () => { live.current = false; clearTimeout(timer); };
  }, [refresh]);

  useEffect(() => {
    if (connection && !loadedUrl) { setUrl(connection.url); setLoadedUrl(true); }
  }, [connection, loadedUrl]);

  useEffect(() => {
    let cancelled = false;
    setVoiceLoadFailed(false);
    if (!project) { setLoadingVoice(false); return; }
    setLoadingVoice(true);
    void apiClient.get<{ voice_id: string; language: string }>(`/projects/${project}`).then(({ data }) => {
      if (!cancelled) { setVoice(data.voice_id); setProjectLanguage(data.language); }
    }).catch(err => {
      if (!cancelled) { setError(errorText(err)); setVoiceLoadFailed(true); }
    }).finally(() => { if (!cancelled) setLoadingVoice(false); });
    return () => { cancelled = true; };
  }, [project]);

  async function act(key: string, action: () => Promise<void>) {
    setBusy(key); setError(""); setNotice("");
    try { await action(); await refresh(); } catch (err) { setError(errorText(err)); }
    finally { setBusy(""); }
  }

  function changeConnection(field: "url" | "token", value: string) {
    version.current += 1; setChecked(null);
    if (field === "url") setUrl(value); else setToken(value);
  }

  async function check(event: FormEvent) {
    event.preventDefault();
    const current = version.current;
    await act("check", async () => {
      const { data } = await apiClient.post<Checked>("/connections/audio/check", { url, token }, local);
      if (version.current === current) { setChecked(data); setNotice("Kết nối hợp lệ. Chọn Lưu hoặc Lưu và tiếp tục các tác vụ đã chọn."); }
    });
  }

  async function save(resumeSelected: boolean) {
    if (!checked) return;
    await act("save", async () => {
      await apiClient.put("/connections/audio", { url, token, fingerprint: checked.fingerprint }, local);
      setToken(""); setChecked(null);
      if (resumeSelected) {
        const failed: number[] = [];
        for (const id of selected) {
          try { await apiClient.post(`/audio/tasks/${id}/resume`, {}, local); } catch { failed.push(id); }
        }
        setSelected(failed);
        setNotice(failed.length ? `Đã lưu kết nối. Cần kiểm tra lại tác vụ: ${failed.join(", ")}.` : "Đã tiếp tục các tác vụ đã chọn.");
      } else setNotice("Đã lưu. Chọn Tiếp tục cho tác vụ bạn muốn chạy.");
    });
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (loadingVoice || voiceLoadFailed || unavailableVoice) return;
    await act("create", async () => {
      await apiClient.post("/audio/tasks", { text, project_id: project ? Number(project) : null,
        title: project ? `Giọng đọc: ${projects.find(p => p.id === Number(project))?.name ?? project}` : "Giọng đọc mới",
        voice, language: selectedVoice?.language ?? projectLanguage, speed }, local);
      setText(""); setNotice("Đã lưu tác vụ. Khi Colab chưa kết nối, bạn có thể tiếp tục sau.");
    });
  }

  const waiting = tasks.filter(t => ["waiting_resource", "needs_attention"].includes(t.status));
  const active = tasks.some(t => ["queued", "running", "cancel_requested"].includes(t.status));
  // Only a saved connection/batch profile is used by the backend for synthesis.
  const voices = connection?.voices ?? [];
  const selectedVoice = voices.find(v => v.id === voice);
  const unavailableVoice = voices.length > 0 && !selectedVoice;

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 pb-24 sm:px-6">
      <Link to="/projects" className="inline-flex items-center gap-2 text-sm text-emerald-300"><ArrowLeft size={16} /> Dự án của tôi</Link>
      <header className="my-6 flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-xs uppercase tracking-widest text-zinc-500">AIFlow / Sản xuất âm thanh</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Colab & giọng đọc</h1>
          <p className="mt-2 max-w-2xl text-sm text-zinc-400">Bật Colab khi cần tạo audio. Các đoạn đã hoàn thành được giữ trên máy để bạn tiếp tục từ phần còn thiếu.</p></div>
        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 px-3 py-2 text-sm text-zinc-300">
          <Plug size={16} /> {labels[connection?.state ?? "not_configured"] ?? connection?.state}
        </span>
      </header>
      {error && <div role="alert" className="mb-5 flex gap-2 rounded-xl border border-rose-500/25 bg-rose-500/10 p-4 text-sm text-rose-200"><WarningCircle size={20} className="shrink-0" />{error}</div>}
      {notice && <p role="status" className="mb-5 flex gap-2 text-sm text-emerald-300"><CheckCircle size={20} />{notice}</p>}
      {waiting.length > 0 && <section className="mb-6 border-l-2 border-amber-400 bg-amber-400/5 p-4">
        <h2 className="font-medium">{waiting.length} tác vụ cần thao tác</h2>
        <p className="mt-1 text-sm text-zinc-400">Chọn tác vụ bên dưới, bật notebook, nhập URL và token rồi lưu để tiếp tục.</p>
      </section>}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(340px,0.75fr)]">
        <section aria-labelledby="queue-title" className="min-w-0">
          <div className="mb-4 flex items-center justify-between"><h2 id="queue-title" className="text-lg font-semibold">Hàng đợi audio</h2><span className="text-sm text-zinc-500">{tasks.length} tác vụ gần nhất</span></div>
          {loading ? <p role="status" className="p-6 text-zinc-400">Đang tải hàng đợi…</p> : tasks.length === 0 ?
            <div className={`${card} p-8`}><Waveform size={30} className="mb-3 text-emerald-400" /><h3>Chưa có tác vụ âm thanh</h3><p className="mt-2 text-sm text-zinc-400">Nhập lời đọc hoặc chọn một dự án trong phần Tạo giọng đọc. Chưa cần bật Colab.</p></div> :
            <ul className="divide-y divide-white/10 rounded-xl border border-white/10">
              {tasks.map(task => <li key={task.id} className="p-4 sm:p-5">
                <div className="flex items-start gap-3">
                  {["waiting_resource", "needs_attention"].includes(task.status) && <input aria-label={`Chọn tác vụ ${task.id}`} type="checkbox" checked={selected.includes(task.id)}
                    onChange={e => setSelected(s => e.target.checked ? [...s, task.id] : s.filter(id => id !== task.id))} className="mt-1 h-5 w-5 accent-emerald-500" />}
                  <div className="min-w-0 flex-1"><h3 className="break-words font-medium">{task.title}</h3>
                    <p className="mt-1 text-xs text-zinc-400">#{task.id} · {task.voice} · {labels[task.status] ?? task.status}</p>
                    {task.generation_job_id && <p className="mt-1 text-xs text-zinc-400">Audio xong sẽ tiếp tục job video #{task.generation_job_id} đã khởi chạy.</p>}
                  </div>
                </div>
                {task.total_segments > 0 && <div className="mt-3"><progress className="h-1.5 w-full accent-emerald-500" value={task.completed_segments} max={task.total_segments} aria-label={`Tiến độ tác vụ ${task.id}`} /><p className="mt-1 text-xs text-zinc-500">{task.completed_segments}/{task.total_segments} đoạn đã lưu</p></div>}
                {task.error && <p className="mt-2 text-sm text-amber-200">{task.error}</p>}
                {task.audio_url && <audio controls preload="none" src={task.audio_url} className="mt-3 w-full" />}
                <div className="mt-3 flex flex-wrap gap-2">
                  {["waiting_resource", "needs_attention"].includes(task.status) && <button className={btnPrimary} disabled={!!busy} onClick={() => void act(`resume-${task.id}`, async () => { await apiClient.post(`/audio/tasks/${task.id}/resume`, {}, local); })}>Tiếp tục</button>}
                  {!["succeeded", "cancelled", "cancel_requested"].includes(task.status) && <button className={btnGhost} disabled={!!busy} onClick={() => void act(`cancel-${task.id}`, async () => { await apiClient.post(`/audio/tasks/${task.id}/cancel`, {}, local); })}>Hủy tác vụ</button>}
                  {task.audio_url && <a className={btnGhost} href={task.audio_url} download>Tải WAV</a>}
                  {task.project_id && <Link className={btnGhost} to={`/timeline/${task.project_id}`}>Mở dự án</Link>}
                  {["waiting_resource", "needs_attention"].includes(task.status) && <>
                    <a className={btnGhost} href={`/api/audio/tasks/${task.id}/batch`}>Xuất batch JSON</a>
                    <label className={`${btnGhost} cursor-pointer`}>Nhập ZIP kết quả<input type="file" accept=".zip" className="sr-only" disabled={!!busy} onChange={e => {
                      const file = e.target.files?.[0]; if (!file) return;
                      void act(`import-${task.id}`, async () => { const form = new FormData(); form.append("file", file); await apiClient.post(`/audio/tasks/${task.id}/import`, form, { headers: { "X-AIFlow-Client": "1", "Content-Type": "multipart/form-data" } }); }); e.target.value = "";
                    }} /></label>
                  </>}
                </div>
              </li>)}
            </ul>}
          {!active && connection?.configured && <p className="mt-4 rounded-lg border border-emerald-500/20 p-4 text-sm text-zinc-300">Không còn tác vụ audio đang xử lý. Nếu đã xong, hãy chọn <strong>Disconnect and delete runtime</strong> trong Colab để giải phóng tài nguyên.</p>}
        </section>
        <div className="space-y-6">
          <section className={`${card} p-5`} aria-labelledby="connection-title">
            <h2 id="connection-title" className="text-lg font-semibold">Kết nối Colab theo phiên</h2>
            <ol className="my-4 space-y-2 text-sm text-zinc-400">
              <li>1. <a href="/api/audio/notebook" className="text-emerald-300 underline">Tải notebook</a> và <a href="/api/audio/worker-bundle" className="text-emerald-300 underline">gói worker</a>.</li>
              <li>2. <a href="https://colab.research.google.com/" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-emerald-300 underline">Mở Colab <ArrowSquareOut size={13} /></a>, tải notebook lên, chọn GPU và chạy hướng dẫn.</li>
              <li>3. Dán URL và token của phiên vào đây.</li>
            </ol>
            <form onSubmit={e => void check(e)} className="space-y-4">
              <label className="block text-sm">URL API Colab<input className={`${inputCls} mt-1 w-full`} type="url" required value={url} autoComplete="off" placeholder="https://your-session.trycloudflare.com" onChange={e => changeConnection("url", e.target.value)} /></label>
              <label className="block text-sm">Token truy cập<input className={`${inputCls} mt-1 w-full`} type="password" required minLength={32} value={token} autoComplete="off" placeholder={connection?.configured ? "Đã lưu token trong phiên backend" : "Token do notebook tạo"} onChange={e => changeConnection("token", e.target.value)} /></label>
              <p className="text-xs text-zinc-500">Token chỉ giữ trong phiên backend. Kiểm tra kết nối không tạo âm thanh.</p>
              <button type="submit" className={btnGhost} disabled={!!busy}>{busy === "check" ? "Đang kiểm tra…" : "Kiểm tra kết nối"}</button>
            </form>
            {checked && <div role="status" className="mt-4 space-y-3 border-t border-white/10 pt-4"><p className="text-sm text-emerald-300">Worker sẵn sàng · {checked.health.engine} · {checked.voices.length} giọng</p>
              <div className="flex flex-wrap gap-2"><button className={btnPrimary} disabled={!!busy} onClick={() => void save(false)}>Lưu kết nối</button><button className={btnGhost} disabled={!!busy || selected.length === 0} onClick={() => void save(true)}>Lưu và tiếp tục {selected.length} tác vụ</button></div></div>}
            {connection?.configured && <button className={`${btnGhost} mt-4`} disabled={!!busy} onClick={() => void act("disconnect", async () => { await apiClient.post("/connections/audio/disconnect", {}, local); setNotice("Đã ngắt API. Thao tác này không tắt GPU Colab."); })}>Ngắt API</button>}
            <details className="mt-5 text-sm text-zinc-400"><summary className="cursor-pointer">Dùng batch khi không có tunnel</summary><p className="my-3">Dán JSON profile không chứa token từ notebook, lưu profile, sau đó xuất JSON từng tác vụ và nhập ZIP kết quả.</p>
              <label className="block">Profile notebook<textarea value={profile} onChange={e => setProfile(e.target.value)} className={`${inputCls} mt-1 min-h-24 w-full`} /></label>
              <button className={`${btnGhost} mt-2`} disabled={!!busy || !profile.trim()} onClick={() => void act("profile", async () => { await apiClient.post("/connections/audio/batch-profile", JSON.parse(profile), local); setNotice("Đã lưu profile batch. Có thể xuất JSON tác vụ."); })}>Lưu profile batch</button>
            </details>
          </section>
          <section className={`${card} p-5`} aria-labelledby="create-title"><h2 id="create-title" className="text-lg font-semibold">Tạo giọng đọc</h2>
            <form onSubmit={e => void create(e)} className="mt-4 space-y-4">
              <label className="block text-sm">Nguồn nội dung<select className={`${inputCls} mt-1 w-full`} value={project} disabled={!!busy} onChange={e => { setLoadingVoice(!!e.target.value); setVoiceLoadFailed(false); setProject(e.target.value); }}><option value="">Nhập lời đọc riêng</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
              {!project && <label className="block text-sm">Lời đọc theo ngôn ngữ giọng đã chọn<textarea required maxLength={50000} value={text} onChange={e => setText(e.target.value)} className={`${inputCls} mt-1 min-h-36 w-full`} placeholder="Paste your approved narration here…" /></label>}
              {project && <p className="text-xs text-zinc-400">Lấy lời đọc đã lưu của dự án. Lưu thay đổi ở Timeline trước khi tạo tác vụ.</p>}
              <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm">Giọng đọc Colab<select className={`${inputCls} mt-1 w-full`} value={voice} disabled={!!busy || loadingVoice || !voices.length} onChange={e => setVoice(e.target.value)}>{!selectedVoice && <option value={voice}>{voice} ({voices.length ? "không có trong profile" : "chờ danh sách giọng"})</option>}{voices.map(v => <option key={v.id} value={v.id}>{v.name} · {v.gender === "female" ? "Nữ" : v.gender === "male" ? "Nam" : "Giọng đọc"} · {v.language}</option>)}</select></label>
                <label className="block text-sm">Tốc độ<input className={`${inputCls} mt-1 w-full`} type="number" min={0.5} max={2} step={0.05} value={speed} onChange={e => setSpeed(Number(e.target.value))} /></label></div>
              {loadingVoice && <p role="status" className="text-sm text-zinc-400">Đang tải giọng đã lưu của dự án…</p>}
              {!voices.length && <p className="text-sm text-zinc-400">Kiểm tra và lưu kết nối Colab hoặc nhập profile batch để tải danh sách giọng. Khi chưa có profile, tác vụ sẽ chờ kết nối.</p>}
              {unavailableVoice && <p role="alert" className="text-sm text-amber-200">Giọng {voice} không có trong profile hiện tại. Hãy chọn một giọng có sẵn trước khi tạo audio.</p>}
              {voiceLoadFailed && <p className="text-sm text-amber-200">Chưa tải được giọng của dự án. Chọn lại dự án để thử lại.</p>}
              {selectedVoice && <p className="text-sm text-zinc-400">Đã chọn: <strong className="text-zinc-200">{selectedVoice.name}</strong> ({selectedVoice.id}). {selectedVoice.description}{project ? " Giọng này sẽ được lưu cho dự án khi tạo tác vụ." : ""}</p>}
              <p className="text-xs text-zinc-400">Ngôn ngữ theo giọng và worker đang kết nối. Danh sách giữ từ kết nối/profile đã lưu; đổi worker thì kiểm tra và lưu lại. Đổi giọng chỉ áp dụng cho tác vụ mới, không đổi tác vụ đang chờ.</p>
              <button className={btnPrimary} type="submit" disabled={!!busy || loadingVoice || voiceLoadFailed || unavailableVoice}>{busy === "create" ? "Đang lưu…" : "Tạo tác vụ giọng đọc"}</button>
            </form>
          </section>
        </div>
      </div>
    </main>
  );
}
