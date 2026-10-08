import { useCallback, useEffect, useRef, useState } from "react";
import { Link, NavLink, useSearchParams } from "react-router-dom";
import ProductionActions from "../components/ProductionActions";

const base = "/api/production";
const field = "w-full rounded-lg border border-white/15 bg-zinc-900 p-3 text-sm";
const button = "rounded-lg border border-white/20 px-4 py-2 text-sm hover:bg-white/10 disabled:opacity-40";
const panel = "rounded-xl border border-white/10 bg-zinc-900/40 p-5 space-y-4";
type Project = { id: number; title: string; kind: string; status: string; channel: string };
type Output = { id: number; project_id: number; job_id: number; kind: string; status: string; error?: string };
type Task = { id: number; project_id: number; status: string; type?: string; title?: string };
type Overview = { projects: Project[]; outputs: Output[]; jobs: Task[]; audio: Task[] };
type Media = { id: number; role: string; scene_id?: number; mime: string; approved: boolean; width: number; height: number; sha256: string; generation_mode?: string; person_media_id?: number; garment_media_id?: number };
type VideoOperation = { request_id: string; scene_id: number; status: string; error: string; can_resume: boolean; allow_silent_video?: boolean; reference_mode?: "ingredients" | "first_frame" };
type FlowCapability = { available: boolean; project_url: string; message: string };
type Detail = Project & { aspect: string; brief: Record<string, string>; prompt: string; media: Media[]; video_operations: VideoOperation[]; scenes: { id: number; order: number; prompt: string; narration: string; duration: number; has_audio: boolean }[] };
type Delivery = Output & { manifest: { files?: Record<string, { bytes: number }>; error?: string; actual_duration?: number } };

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(base + path, { method, headers: { "X-AIFlow-Client": "1", ...(body instanceof FormData ? {} : { "Content-Type": "application/json" }) }, body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Không xử lý được yêu cầu. Kiểm tra nội dung nhập.");
  return result;
}

export function WorkspaceNav() {
  return <header className="border-b border-white/10 px-4 py-3"><nav aria-label="Điều hướng xưởng" className="mx-auto flex max-w-7xl flex-wrap items-center gap-2 text-sm"><Link to="/" className="mr-4 font-semibold">AIFlow / Studio</Link>{[["/", "Tổng quan"], ["/scripts", "Kịch bản"], ["/production", "Sản xuất"], ["/connections", "Colab & audio"], ["/voice-training", "Huấn luyện giọng"], ["/studio-settings", "Kết nối & series"], ["/work-queue", "Tác vụ"], ["/library", "Thư viện"], ["/projects", "Dự án cũ"]].map(([to, label]) => <NavLink key={to} to={to} end className={({ isActive }) => `rounded-md px-3 py-2 ${isActive ? "bg-emerald-400/10 text-emerald-300" : "text-zinc-400 hover:text-white"}`}>{label}</NavLink>)}</nav></header>;
}

function Checklist({ entries, onSubmit, busy }: { entries: [string, string][]; onSubmit: (checklist: string[]) => void; busy: boolean }) {
  const [checked, setChecked] = useState<string[]>([]);
  return <div className="space-y-3">{entries.map(([id, label]) => <label key={id} className="flex items-start gap-3 text-sm"><input type="checkbox" checked={checked.includes(id)} onChange={e => setChecked(e.target.checked ? [...checked, id] : checked.filter(x => x !== id))} className="mt-1" />{label}</label>)}<button className={button} disabled={busy || checked.length !== entries.length} onClick={() => onSubmit(checked)}>Xác nhận đã kiểm tra</button></div>;
}

export default function ProductionStudio({ view = "production" }: { view?: "production" | "overview" | "queue" | "library" }) {
  const [params, setParams] = useSearchParams();
  const selected = Number(params.get("project")) || 0;
  const selectedOutput = Number(params.get("output")) || 0;
  const currentSelection = useRef(selected);
  currentSelection.current = selected;
  const [overview, setOverview] = useState<Overview>({ projects: [], outputs: [], jobs: [], audio: [] });
  const [detail, setDetail] = useState<Detail | null>(null);
  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const currentDelivery = useRef(0);
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loop, setLoop] = useState(false);
  const [subtitleMode, setSubtitleMode] = useState("scene");
  const [stillMotion, setStillMotion] = useState(false);
  const [channel, setChannel] = useState("");
  const videoRequests = useRef<Record<number, string>>({});
  const [flowCapability, setFlowCapability] = useState<FlowCapability | null>(null);
  const [flowProjectUrl, setFlowProjectUrl] = useState("");
  const [referenceMediaId, setReferenceMediaId] = useState(0);
  const [referenceNote, setReferenceNote] = useState("");
  const [referenceMode, setReferenceMode] = useState<"ingredients" | "first_frame">("ingredients");
  const [allowSilentVideo, setAllowSilentVideo] = useState(false);
  const referenceProject = useRef(selected);
  const [copiedScene, setCopiedScene] = useState<number | null>(null);
  const [resolvedChecks, setResolvedChecks] = useState<Record<string, boolean>>({});
  const refresh = useCallback(async () => {
    const nextOverview = await request<Overview>("/overview");
    if (currentSelection.current !== selected) return;
    setOverview(nextOverview);
    const next = selected ? await request<Detail>(`/projects/${selected}`) : null;
    if (currentSelection.current === selected) setDetail(next);
    const outputId = currentDelivery.current;
    if (outputId) {
      const nextDelivery = await request<Delivery>(`/outputs/${outputId}`);
      if (currentSelection.current === selected && currentDelivery.current === outputId && (!selected || nextDelivery.project_id === selected)) setDelivery(nextDelivery);
    }
  }, [selected]);
  useEffect(() => { let active = true; setLoading(true); setError(""); setDetail(null); setDelivery(null); currentDelivery.current = 0; setLoop(false); setSubtitleMode("scene"); setStillMotion(false); refresh().catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); }); const timer = setInterval(() => { refresh().catch(() => {}); }, 5000); return () => { active = false; clearInterval(timer); }; }, [refresh]);
  useEffect(() => {
    let active = true;
    currentDelivery.current = selectedOutput;
    setDelivery(null);
    if (selectedOutput) request<Delivery>(`/outputs/${selectedOutput}`).then(result => {
      if (active && currentSelection.current === selected && currentDelivery.current === selectedOutput) {
        if (selected && result.project_id !== selected) setError("Thành phẩm không thuộc dự án đang chọn.");
        else setDelivery(result);
      }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [selected, selectedOutput]);
  useEffect(() => { setStatus(""); setKind(""); setSearch(""); }, [view]);
  useEffect(() => { setChannel(detail?.brief.channel || ""); }, [detail?.id]);
  useEffect(() => {
    let active = true;
    setFlowCapability(null); setFlowProjectUrl(""); setCopiedScene(null); setResolvedChecks({});
    if (referenceProject.current !== selected) {
      referenceProject.current = selected;
      setReferenceMediaId(0); setReferenceNote("");
      setReferenceMode("ingredients");
      setAllowSilentVideo(false); videoRequests.current = {};
    }
    if (detail?.kind === "video") request<FlowCapability>("/flow-capability").then(result => { if (active) { setFlowCapability(result); if (result.project_url.includes("/project/")) setFlowProjectUrl(result.project_url); } }).catch(() => {
      if (active) setFlowCapability({ available: false, project_url: "https://flow.google.com/", message: "Chưa kiểm tra được Bridge. Chọn URL dự án đã đăng nhập, kiểm tra kết nối extension rồi thử lại." });
    });
    return () => { active = false; };
  }, [selected, detail?.id, detail?.kind]);
  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : "Không hoàn tất thao tác."); } finally { setBusy(false); }
  }
  function openOutput(output: Output) {
    setParams({ ...(selected ? { project: String(selected) } : {}), output: String(output.id) });
  }
  async function connectFlowProject() {
    const result = await request<FlowCapability>("/flow-project", "POST", { url: flowProjectUrl });
    if (currentSelection.current === selected) {
      setFlowProjectUrl(result.project_url);
      setFlowCapability(result);
    }
  }
  async function upload(file: File, role: string, scene?: number) {
    const form = new FormData(); form.set("file", file); form.set("role", role); if (scene) form.set("scene_id", String(scene));
    if (role === "reference" && detail?.kind === "video") form.set("provenance_note", referenceNote);
    const media = await request<Media>(`/projects/${selected}/media`, "POST", form);
    if (role === "reference" && detail?.kind === "video") setReferenceMediaId(media.id);
  }
  function uploadControl(role: string, scene?: number) {
    return <label className="block space-y-2 text-sm text-zinc-300">{role === "garment" ? "Thêm ảnh trang phục shop (trải phẳng, nền sạch)" : role === "reference" ? detail?.kind === "video" ? referenceMode === "first_frame" ? "Thêm PNG khung hình đầu (tối đa 5 MiB)" : "Thêm PNG tham chiếu nhân vật / trang phục (tối đa 5 MiB)" : "Thêm ảnh tham chiếu (1–3 ảnh)" : role === "portrait" ? "Nhập chân dung đã tạo bằng dịch vụ AI bên ngoài" : "Nhập ảnh hoặc MP4 cho cảnh"}<input className={field} type="file" accept={role === "reference" && detail?.kind === "video" ? "image/png" : role === "visual" ? "image/png,image/jpeg,image/webp,video/mp4" : "image/png,image/jpeg,image/webp"} disabled={busy || detail?.status === "generating"} onChange={e => { const file = e.target.files?.[0]; if (file) void act(() => upload(file, role, scene)); e.target.value = ""; }} /></label>;
  }
  function videoControl(scene: { id: number; prompt: string }) {
    const sceneId = scene.id;
    const operations = (detail?.video_operations ?? []).filter(item => item.scene_id === sceneId);
    const unresolved = operations.find(item => ["running", "interrupted", "needs_attention"].includes(item.status));
    const projectVideoRunning = detail?.video_operations.some(item => item.status === "running");
    return <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy} onClick={() => void act(async () => { const approved = await request<{ prompt: string }>(`/projects/${selected}/scenes/${sceneId}/flow-prompt`); await navigator.clipboard.writeText(approved.prompt); setCopiedScene(sceneId); })}>Chép prompt cảnh{copiedScene === sceneId ? " · Đã chép" : ""}</button>
      </div>
      <p className="text-xs text-zinc-400">Bridge dùng prompt đã duyệt và thao tác giao diện Flow để tạo Veo 3.1 Lite / 8 giây, khung hình {detail?.aspect}. Clip được nhận vào cảnh và cần duyệt trước khi xuất.</p>
      {flowCapability?.message && <p className="text-sm text-amber-200">{flowCapability.message}</p>}
      {projectVideoRunning && <p className="text-sm text-amber-200" role="status">Dự án đang tạo / nhận một clip Flow. Chờ tác vụ hiện tại hoàn tất rồi tạo cảnh tiếp theo.</p>}
      <button className={button} disabled={busy || projectVideoRunning || !flowCapability?.available || !!unresolved || detail?.status === "generating" || detail?.aspect === "1:1" || (!!referenceMediaId && !detail?.media.some(m => m.id === referenceMediaId && m.role === "reference" && m.approved)) || (referenceMode === "first_frame" && !detail?.media.some(m => m.id === referenceMediaId && m.role === "reference" && m.approved && m.mime === "image/png"))} onClick={() => void act(async () => {
        const requestId = videoRequests.current[sceneId] ?? crypto.randomUUID();
        videoRequests.current[sceneId] = requestId;
        await request(`/projects/${selected}/generate-video`, "POST", { request_id: requestId, scene_id: sceneId, reference_media_id: referenceMediaId || null, reference_mode: referenceMode, allow_silent_video: allowSilentVideo });
        delete videoRequests.current[sceneId];
      })}>Tạo video Veo Lite qua Bridge</button>
      <button className={`${button} ml-2`} disabled={busy} onClick={() => void act(async () => setFlowCapability(await request<FlowCapability>("/flow-capability")))}>Kiểm tra khả năng Bridge</button>
      <p className="text-xs text-zinc-400">Bridge chỉ tạo khi Google Flow cho phép; mỗi lượt tạo dùng credit của tài khoản.</p>
      {operations.map(operation => <div key={operation.request_id} className="text-sm text-zinc-400" role="status">
        Veo Lite · {({ running: "Đang tạo / nhận clip", succeeded: "Đã nhận clip, cần duyệt", failed: "Chưa tạo được", interrupted: "Bị gián đoạn", needs_attention: "Cần xử lý", resolved: "Đã kiểm tra và khép lại" } as Record<string, string>)[operation.status] ?? operation.status}
        {operation.reference_mode && <p>Chế độ: {operation.reference_mode === "first_frame" ? "Khung hình đầu" : "Ảnh tham chiếu nhân vật / trang phục"}</p>}
        {operation.allow_silent_video && <p>Đã cho phép nhận clip không có âm thanh nếu Flow tạo âm thanh lỗi.</p>}
        {operation.error && <p className="text-amber-200">{operation.error}</p>}
        {["interrupted", "needs_attention"].includes(operation.status) && operation.can_resume && <button className={`${button} mt-2`} disabled={busy} onClick={() => void act(() => request(`/video-operations/${operation.request_id}/resume`, "POST"))}>Tiếp tục nhận clip (không tạo lại)</button>}
        {["interrupted", "needs_attention"].includes(operation.status) && !operation.can_resume && <div className="mt-2 space-y-2">
          <label className="flex items-start gap-2"><input type="checkbox" checked={!!resolvedChecks[operation.request_id]} onChange={event => setResolvedChecks(current => ({ ...current, [operation.request_id]: event.target.checked }))} />Đã kiểm tra Google Flow và xử lý lượt này; không cần tiếp tục nhận kết quả.</label>
          <button className={button} disabled={busy || !resolvedChecks[operation.request_id]} onClick={() => void act(() => request(`/video-operations/${operation.request_id}/resolve`, "POST", { checked_flow: true }))}>Khép lại lượt đã kiểm tra</button>
        </div>}
      </div>)}
    </div>;
  }
  function mediaCard(item: Media) {
    const vton = item.generation_mode === "vton";
    const entries: [string, string][] = item.role === "reference" ? [["identity", "Ảnh đúng người và đặc điểm nhận diện cần giữ"], ["clothing", "Trang phục, phụ kiện đúng và đủ rõ"], ["rights", "Có quyền dùng ảnh này làm tham chiếu"]] : item.role === "portrait" ? [["likeness", "Khuôn mặt, màu mắt, tóc / bộ lông và đặc điểm nhận diện đúng brief hoặc ảnh tham chiếu (nếu có)"], ["anatomy", "Hình thể và các chi tiết giải phẫu đúng"], ["crop", "Bố cục và vùng cắt phù hợp"], ["artifacts", "Không có chi tiết lỗi hoặc chữ rác"]] : [["content", "Đúng nội dung cảnh"], ["continuity", "Nhân vật và bối cảnh liên tục"], ["framing", "Khung hình, giải phẫu và chi tiết đạt yêu cầu"]];
    if (vton) entries.push(["garment_fidelity", "Đã so với sản phẩm shop: màu, phom, chất liệu, họa tiết và logo đúng; không có chi tiết tự thêm"]);
    return <article key={item.id} className={panel}>
      {vton && <><h4 className="font-medium">So sánh ảnh thử trang phục #{item.id}</h4><div className="grid grid-cols-2 gap-3">{[[item.person_media_id, "Người gốc"], [item.garment_media_id, "Sản phẩm shop gốc"]].map(([id, label]) => typeof id === "number" && <figure key={String(label)}><img loading="lazy" src={`${base}/media/${id}`} alt={`${label} của ảnh ${item.id}`} className="max-h-64 w-full object-contain" /><figcaption className="mt-1 text-center text-xs text-zinc-400">{label}</figcaption></figure>)}</div></>}
      {item.mime.startsWith("video") ? <video controls preload="metadata" src={`${base}/media/${item.id}`} className="max-h-80 w-full" /> : <img loading="lazy" src={`${base}/media/${item.id}`} alt={`${item.role === "reference" ? "Ảnh tham chiếu" : item.role === "garment" ? "Trang phục shop" : vton ? "Kết quả thử trang phục" : "Ảnh cần duyệt"} ${item.id}`} className="max-h-80 w-full object-contain" />}
      {vton && <p className="text-center text-xs text-zinc-400">Kết quả thử trang phục</p>}
      <p className="text-sm text-zinc-400">#{item.id} · {item.width} × {item.height}px · {item.approved ? "Đã duyệt" : item.role === "reference" ? "Tham chiếu" : item.role === "garment" ? "Sản phẩm shop" : "Chưa duyệt"}</p>
      {vton && <p className="text-xs text-zinc-400">Kiểm tra cả người và sản phẩm trước khi duyệt. Ảnh thử đồ không xác nhận size hoặc độ vừa thực tế.</p>}
      {!item.approved && item.role !== "garment" && (item.role !== "reference" || detail?.kind === "video") && <Checklist busy={busy} entries={entries} onSubmit={checklist => void act(() => request(`/media/${item.id}/review`, "POST", { checklist }))} />}
      <button className={button} disabled={busy || detail?.status === "generating"} onClick={() => void act(() => request(`/media/${item.id}`, "DELETE"))}>Lưu trữ bản này</button>
    </article>;
  }
  const projects = overview.projects.filter(p => (!kind || p.kind === kind) && (!status || p.status === status) && `${p.title} ${p.channel}`.toLowerCase().includes(search.toLowerCase()));
  const outputs = overview.outputs.filter(o => !selected || o.project_id === selected);
  return <main className="mx-auto max-w-7xl space-y-7 px-4 py-8 pb-24 sm:px-8">
    <div><p className="text-xs uppercase tracking-widest text-emerald-400">Xưởng cá nhân · nhiều kênh</p><h1 className="mt-2 text-3xl font-semibold">{{ production: "Sản xuất & duyệt thành phẩm", overview: "Hôm nay cần làm gì?", queue: "Tác vụ & khôi phục", library: "Thư viện theo dự án" }[view]}</h1><p className="mt-3 max-w-3xl text-zinc-400">Duyệt kịch bản → chuẩn bị lời đọc và hình ảnh → xem thành phẩm → tải bộ file. Mỗi lượt xuất giữ một bản chụp dữ liệu riêng.</p></div>
    {error && <div role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4">{error}<button className={`${button} ml-3`} onClick={() => void act(refresh)}>Thử tải lại</button></div>}
    {loading && <p role="status">Đang tải dữ liệu xưởng…</p>}
    {view === "library" && <div className="flex flex-wrap gap-3"><Link className={button} to="/voices">Thư viện giọng</Link><Link className={button} to="/new-project">Adapter & phong cách</Link><Link className={button} to="/scripts">Phiên bản kịch bản</Link></div>}{view === "overview" && <section className={panel}><h2 className="text-lg font-semibold">Việc đang chờ</h2><p>{overview.outputs.filter(o => o.status === "awaiting_review").length} thành phẩm chờ duyệt · {overview.audio.filter(a => a.status === "waiting_resource").length} tác vụ chờ Colab</p><div className="flex flex-wrap gap-3"><Link className={button} to="/scripts">Viết kịch bản</Link><Link className={button} to="/production">Làm chân dung / video</Link><Link className={button} to="/connections">Bật Colab và nhập URL</Link></div></section>}
    {view === "queue" ? <section className={panel}><label className="block">Lọc trạng thái<select value={status} onChange={e => setStatus(e.target.value)} className={field}><option value="">Tất cả</option>{Array.from(new Set([...overview.jobs, ...overview.audio].map(t => t.status))).map(s => <option key={s}>{s}</option>)}</select></label>{[...overview.audio.map(t => ({ ...t, group: "audio" })), ...overview.jobs.map(t => ({ ...t, group: "job" }))].filter(t => !status || t.status === status).map(t => <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 py-3" key={`${t.group}-${t.id}`}><div><p>{t.group} #{t.id} · {t.type || t.title}</p><p className="text-sm text-zinc-400">{t.status} · dự án {t.project_id || "audio độc lập"}</p></div><div className="flex gap-2"><Link className={button} to={t.group === "audio" ? "/queue" : `/production?project=${t.project_id}${overview.outputs.find(o => o.job_id === t.id) ? `&output=${overview.outputs.find(o => o.job_id === t.id)!.id}` : ""}`}>{t.group === "audio" ? "Mở hàng đợi audio" : "Mở dự án / kết quả"}</Link>{t.type === "production_render" && ["pending", "running"].includes(t.status) && <button className={button} disabled={busy} onClick={() => void act(() => request(`/jobs/${t.id}/cancel`, "POST"))}>Hủy sau công đoạn hiện tại</button>}</div></div>)}{!overview.audio.length && !overview.jobs.length && <p>Chưa có tác vụ. Tạo kịch bản hoặc dự án để bắt đầu.</p>}</section> : <>
    <section className={panel}><h2 className="text-lg font-semibold">Dự án</h2><div className="grid gap-3 sm:grid-cols-3"><input aria-label="Tìm dự án hoặc kênh" className={field} placeholder="Tìm tên dự án hoặc kênh…" value={search} onChange={e => setSearch(e.target.value)} /><select aria-label="Loại dự án" className={field} value={kind} onChange={e => setKind(e.target.value)}><option value="">Mọi loại</option><option value="portrait">Chân dung</option><option value="video">Video</option><option value="legacy">Chưa phân loại</option></select><select aria-label="Trạng thái dự án" className={field} value={status} onChange={e => setStatus(e.target.value)}><option value="">Mọi trạng thái</option>{Array.from(new Set(overview.projects.map(p => p.status))).map(s => <option key={s}>{s}</option>)}</select></div><div className="divide-y divide-white/10">{projects.map(p => <Link key={p.id} to={`${view === "library" ? "/library" : "/production"}?project=${p.id}`} className={`flex flex-wrap justify-between gap-2 py-3 ${selected === p.id ? "text-emerald-300" : ""}`}><span>{p.title} <small className="text-zinc-500">{p.channel || "Chưa gán kênh"}</small></span><span className="text-sm text-zinc-400">{p.kind} · {p.status}</span></Link>)}</div>{!projects.length && <p className="text-zinc-400">Chưa có dự án phù hợp.</p>}</section>
    {view === "library" && detail && <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">Tài nguyên · {detail.title}</h2><Link className={button} to={`/production?project=${detail.id}`}>Mở sản xuất & duyệt</Link></div>
      <div className="grid gap-4 md:grid-cols-3">{detail.media.map(item => <article key={item.id} className="space-y-3 rounded-lg border border-white/10 p-4">
        {item.mime.startsWith("video") ? <video controls preload="metadata" src={`${base}/media/${item.id}`} className="max-h-64 w-full" /> : <img loading="lazy" src={`${base}/media/${item.id}`} alt={`Tài nguyên ${item.id}`} className="max-h-64 w-full object-contain" />}
        <p className="text-sm text-zinc-400">#{item.id} · {{ reference: "Tham chiếu", visual: "Hình / clip cảnh", portrait: "Chân dung", garment: "Trang phục shop" }[item.role] || item.role} · {item.width} × {item.height}px · {item.approved ? "Đã duyệt" : "Chưa duyệt"}{item.scene_id ? ` · Cảnh ${(detail.scenes.find(scene => scene.id === item.scene_id)?.order ?? 0) + 1}` : ""}</p>
        <a className="text-sm text-emerald-300 underline" href={`${base}/media/${item.id}`} download>Tải tài nguyên</a>
      </article>)}</div>
      {!detail.media.length && <p className="text-zinc-400">Chưa có tài nguyên trong xưởng. Mở sản xuất để nhập ảnh/clip hoặc nhận clip từ Timeline.</p>}
    </section>}
    {view === "production" && !selected && <section className={panel}><h2 className="text-xl font-semibold">Chân dung người / thú cưng mới</h2><p className="text-sm text-zinc-400">Tạo ảnh với Colab hoặc Gemini đã cấu hình, hoặc nhập ảnh từ dịch vụ khác rồi duyệt tại đây. AIFlow không chạy AI trên máy.</p><form className="grid gap-4 sm:grid-cols-2" onSubmit={e => { e.preventDefault(); const data = Object.fromEntries(new FormData(e.currentTarget)); void act(async () => { const result = await request<{ id: number }>("/portraits", "POST", data); setParams({ project: String(result.id) }); }); }}>{[["title", "Tên dự án"], ["channel", "Kênh / thương hiệu (tùy chọn)"], ["species", "Chủ thể / loài / giống"], ["style", "Phong cách"], ["identity", "Đặc điểm nhận diện phải giữ"], ["requirements", "Yêu cầu giao hàng (tùy chọn)"]].map(([name, label]) => <label className="space-y-2 text-sm" key={name}>{label}<input name={name} className={field} maxLength={name === "identity" || name === "requirements" ? 5000 : name === "style" ? 1000 : name === "title" ? 200 : 100} required={!["channel", "requirements"].includes(name)} /></label>)}<button disabled={busy} className={button}>Tạo dự án chân dung</button><Link to="/scripts" className={button}>Tạo video từ kịch bản</Link></form></section>}
    {view === "production" && detail && <section className="space-y-5"><div className={panel}><h2 className="text-2xl font-semibold">{detail.title}</h2><p className="text-zinc-400">{detail.kind} · {detail.status}</p><label className="block text-sm">Kênh / thương hiệu<input value={channel} onChange={e => setChannel(e.target.value)} maxLength={100} className={field} /></label><button className={button} disabled={busy || detail.status === "generating"} onClick={() => void act(() => request(`/projects/${selected}/kind`, "PUT", { kind: detail.kind === "legacy" ? "video" : detail.kind, channel }))}>{detail.kind === "legacy" ? "Xác nhận đây là dự án video" : "Lưu kênh"}</button></div>
    <ProductionActions key={detail.id} projectId={detail.id} kind={detail.kind} scenes={detail.scenes} media={detail.media} defaultSubject={detail.kind === "portrait" && !/người|human|person/i.test(detail.brief.species || "") ? "pet" : "human"} onChanged={refresh} />{detail.kind !== "legacy" && <section className={panel}><h3 className="font-semibold">Trang phục shop để thử (VTON)</h3><p className="text-sm text-zinc-400">Nhập ảnh một sản phẩm trải phẳng trên nền sạch, không ghép nhiều ảnh hoặc có người mẫu. Sau đó chọn riêng ảnh người và sản phẩm ở chế độ thử trang phục bên trên.</p>{uploadControl("garment")}<div className="grid gap-4 md:grid-cols-3">{detail.media.filter(m => m.role === "garment").map(mediaCard)}</div></section>}{detail.kind === "portrait" && <><section className={panel}><h3 className="font-semibold">1. Brief & ảnh tham chiếu (nếu có)</h3><pre className="whitespace-pre-wrap break-words text-sm text-zinc-300">{detail.prompt}</pre>{uploadControl("reference")}<div className="grid gap-4 md:grid-cols-3">{detail.media.filter(m => m.role === "reference").map(mediaCard)}</div></section><section className={panel}><h3 className="font-semibold">2. Thành phẩm & độ giống</h3>{uploadControl("portrait")}<p className="text-sm text-zinc-400">Bản mới nhất đang hiển thị đầu tiên sẽ được dùng để xuất. Kiểm tra theo brief và ảnh tham chiếu (nếu có) trước khi duyệt.</p><div className="grid gap-4 md:grid-cols-2">{detail.media.filter(m => m.role === "portrait").map(mediaCard)}</div></section></>}
    {detail.kind === "video" && <><section className={panel}><h3 className="font-semibold">Kết nối dự án Google Flow</h3><label className="block space-y-2 text-sm">URL dự án Google Flow hiện có<input aria-label="URL dự án Google Flow" type="url" className={field} maxLength={512} placeholder="https://flow.google.com/project/UUID" value={flowProjectUrl} onChange={event => setFlowProjectUrl(event.target.value)} disabled={busy || detail.status === "generating"} /></label><button className={button} disabled={busy || !flowProjectUrl.trim() || detail.status === "generating"} onClick={() => void act(connectFlowProject)}>Mở dự án qua Bridge & kiểm tra</button><p className="text-xs text-zinc-400">AIFlow gửi URL qua backend và extension để chọn đúng tab, rồi kiểm tra khả năng tạo trước khi bạn bấm Tạo video Veo Lite.</p>{flowCapability?.message && <p className="text-sm text-amber-200" role="status">{flowCapability.message}</p>}<label className="flex items-start gap-3 text-sm"><input type="checkbox" className="mt-1" checked={allowSilentVideo} disabled={busy || detail.status === "generating" || detail.video_operations.some(operation => operation.status === "running")} onChange={event => { setAllowSilentVideo(event.target.checked); videoRequests.current = {}; }} />Cho phép Flow trả clip không có âm thanh khi phần tạo âm thanh lỗi.</label><p className="text-xs text-zinc-400">Áp dụng cho lượt tạo tiếp theo. Sau khi nhận, nghe và kiểm tra clip trước khi duyệt.</p></section><section className={panel}><h3 className="font-semibold">Tham chiếu khi tạo cảnh</h3><label className="block text-sm">Cách dùng ảnh tham chiếu<select className={field} value={referenceMode} disabled={busy || detail.status === "generating" || detail.video_operations.some(operation => operation.status === "running")} onChange={event => { setReferenceMode(event.target.value as "ingredients" | "first_frame"); setReferenceMediaId(0); setReferenceNote(""); videoRequests.current = {}; }}><option value="ingredients">Ảnh tham chiếu nhân vật / trang phục</option><option value="first_frame">Khung hình đầu — nối từ cuối cảnh trước</option></select></label><p className="text-sm text-zinc-400">{referenceMode === "first_frame" ? "Chọn PNG trích đúng khung cuối của clip cảnh trước đã duyệt để làm khung hình đầu của lượt tạo tiếp theo. Ghi nguồn clip và khung hình bên dưới, tải ảnh lên rồi duyệt ảnh. Vẫn cần kiểm tra chuyển động và điểm nối sau khi tạo." : "Ảnh đã duyệt được gửi từ AIFlow qua Bridge, chọn đúng asset theo SHA và dùng chế độ Thành phần của Flow Lite. Ảnh tham chiếu hỗ trợ giữ người/trang phục; vẫn cần kiểm tra từng clip."}</p><label className="block text-sm">Nguồn ảnh (ví dụ: clip, cảnh và thời điểm trích)<input className={field} maxLength={1000} value={referenceNote} onChange={e => setReferenceNote(e.target.value)} /></label>{uploadControl("reference")}<label className="block text-sm">Tham chiếu dùng cho lượt tạo tiếp theo<select className={field} value={referenceMediaId} disabled={busy || detail.status === "generating" || detail.video_operations.some(operation => operation.status === "running")} onChange={e => { setReferenceMediaId(Number(e.target.value)); videoRequests.current = {}; }}><option value={0}>{referenceMode === "first_frame" ? "Chọn PNG đã duyệt để làm khung hình đầu" : "Không dùng ảnh tham chiếu"}</option>{detail.media.filter(m => m.role === "reference").map(m => <option key={m.id} value={m.id}>Ảnh #{m.id} · {m.sha256.slice(0, 12)} · {m.approved ? "Đã duyệt" : "Cần duyệt trước khi tạo"}</option>)}</select></label><div className="grid gap-4 md:grid-cols-3">{detail.media.filter(m => m.role === "reference").map(mediaCard)}</div></section><div className="flex flex-wrap gap-3"><Link className={button} to="/connections">Chuẩn bị lời đọc trên Colab</Link><Link className={button} to={`/timeline/${selected}`}>Timeline / Flow</Link></div>{detail.scenes.map(scene => <section className={panel} key={scene.id}><h3 className="font-semibold">Cảnh {scene.order + 1} · {scene.duration}s theo kịch bản</h3><p className="text-sm text-zinc-300">{scene.prompt}</p><p className="text-sm text-zinc-400">{scene.narration || "Cảnh im lặng"} · {scene.has_audio ? "Có file audio; sẽ đo khi xuất" : scene.narration ? "Chưa có lời đọc" : "Không cần TTS"}</p>{videoControl(scene)}{uploadControl("visual", scene.id)}<div className="grid gap-4 md:grid-cols-2">{detail.media.filter(m => m.scene_id === scene.id).map(mediaCard)}</div></section>)}</>}
    {detail.kind !== "legacy" && <section className={panel}><h3 className="font-semibold">3. Xuất bản nháp để xem</h3>{detail.kind === "video" && <label className="block text-sm">Cách tạo phụ đề<select className={field} value={subtitleMode} onChange={e => setSubtitleMode(e.target.value)}><option value="scene">Theo cảnh và thời lượng lời đọc (không cần Colab)</option><option value="remote_stt">Nhận dạng trên Colab (cần bật STT)</option></select></label>}{detail.kind === "video" && <><p className="text-sm text-zinc-400">Dùng ảnh/clip mới nhất đã duyệt cho mỗi cảnh. Phụ đề theo cảnh và thời lượng audio thực tế. Giữ khoảng im lặng, không cắt lời đọc.</p><label className="flex gap-3 text-sm"><input type="checkbox" checked={loop} onChange={e => setLoop(e.target.checked)} />Cho phép lặp clip khi clip ngắn hơn lời đọc</label><label className="flex gap-3 text-sm"><input type="checkbox" checked={stillMotion} onChange={e => setStillMotion(e.target.checked)} />Chuyển động zoom nhẹ cho ảnh tĩnh (cắt tối đa 5% vùng rìa)</label></>}<button className={button} disabled={busy || detail.status === "generating"} onClick={() => void act(() => request(`/projects/${selected}/render`, "POST", { allow_loop: loop, subtitle_mode: subtitleMode, still_motion: stillMotion }))}>Xuất lượt mới</button><p className="text-xs text-zinc-500">Lượt xuất lỗi được giữ trong lịch sử; sửa tài nguyên rồi xuất lượt mới.</p></section>}</section>}
    </>}
    <section className={panel}><h2 className="text-xl font-semibold">Thành phẩm {selected ? `· dự án #${selected}` : "gần đây"}</h2>{outputs.map(o => <div key={o.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 py-3"><div>#{o.id} · {o.kind} · {o.status}{o.error && <p className="text-sm text-rose-300">{o.error}</p>}</div><button className={button} disabled={busy} onClick={() => openOutput(o)}>Xem và duyệt</button></div>)}{!outputs.length && <p className="text-zinc-400">Chưa có thành phẩm. ZIP giao hàng chỉ tải được sau bước duyệt cuối.</p>}</section>
    {delivery && <section className={panel}><h2 className="text-xl font-semibold">Duyệt bộ file #{delivery.id}</h2><p>{delivery.status}</p>{delivery.manifest.error && <p role="alert">{delivery.manifest.error}</p>}{delivery.manifest.files && <><div>{delivery.kind === "video" ? <video controls className="mx-auto max-h-[65vh] max-w-full" src={`${base}/outputs/${delivery.id}/file/video.mp4`} /> : <img className="mx-auto max-h-[65vh] max-w-full" alt="Bản xem trước thành phẩm" src={`${base}/outputs/${delivery.id}/file/preview.jpg`} />}</div><ul className="space-y-2 text-sm">{Object.entries(delivery.manifest.files).map(([name, info]) => <li key={name}><a className="text-emerald-300 underline" target="_blank" rel="noreferrer" href={`${base}/outputs/${delivery.id}/file/${name}`}>{name}</a> · {Math.ceil(info.bytes / 1024)} KB</li>)}</ul>{delivery.status === "awaiting_review" && <Checklist key={delivery.id} busy={busy} entries={[["quality", "Đã xem / nghe thành phẩm, không lỗi hình hoặc tiếng"], ["rights", "Có quyền sử dụng và giao các tài nguyên này"], ["delivery", "Đã kiểm tra bộ file, kích thước, phụ đề và nội dung mô tả"]]} onSubmit={checklist => void act(async () => { await request(`/outputs/${delivery.id}/review`, "POST", { checklist }); const result = await request<Delivery>(`/outputs/${delivery.id}`); if (currentSelection.current === selected && currentDelivery.current === result.id) setDelivery(result); })} />}{delivery.status === "approved" && <a className={button} href={`${base}/outputs/${delivery.id}/download`}>Tải ZIP đã duyệt</a>}</>}</section>}
  </main>;
}
