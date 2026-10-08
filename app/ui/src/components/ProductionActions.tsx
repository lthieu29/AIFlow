import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { studioRequest, type ColabImageConnection } from "../pages/StudioSettings";

type ImageOperation = { request_id: string; kind: string; status: string; error: string; input_json?: string; result_json?: string };
type ImageMedia = { id: number; role: string; mime: string; approved: boolean };
const pending = (operation: ImageOperation) => {
  if (["queued", "running"].includes(operation.status)) return true;
  if (operation.status !== "needs_attention") return false;
  try { return !JSON.parse(operation.result_json || "{}").id; } catch { return true; }
};
const colabOperation = (operation: ImageOperation) => {
  try { return JSON.parse(operation.input_json || "{}").provider === "colab"; } catch { return false; }
};
const statuses: Record<string, string> = { queued: "Đang chờ worker", running: "Đang tạo ảnh", succeeded: "Đã nhận ảnh — cần xem và duyệt", failed: "Tạo ảnh thất bại", needs_attention: "Cần kiểm tra lại đầu vào / kết quả", interrupted: "Lượt tạo bị gián đoạn" };

export default function ProductionActions({ projectId, kind, scenes, media, defaultSubject = "human", onChanged }: {
  projectId: number; kind: string; scenes: { id: number; order: number }[]; media: ImageMedia[];
  defaultSubject?: "human" | "pet"; onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [scene, setScene] = useState("");
  const [history, setHistory] = useState<ImageOperation[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [provider, setProvider] = useState<"gemini" | "colab">("gemini");
  const [generationMode, setGenerationMode] = useState<"reference" | "text" | "vton">("reference");
  const [subject, setSubject] = useState<"human" | "pet">(defaultSubject), [prompt, setPrompt] = useState("");
  const [seed, setSeed] = useState(0), [strength, setStrength] = useState(0.45);
  const [steps, setSteps] = useState(30), [guidance, setGuidance] = useState(4.5);
  const [referenceIds, setReferenceIds] = useState<number[]>([]);
  const [personId, setPersonId] = useState(""), [garmentId, setGarmentId] = useState("");
  const [garmentCategory, setGarmentCategory] = useState<"tops" | "bottoms" | "one-pieces">("tops");
  const [connection, setConnection] = useState<ColabImageConnection | null>(null);
  const [unconfirmedRequest, setUnconfirmedRequest] = useState("");
  const [sourceImage, setSourceImage] = useState(""), [targetProject, setTargetProject] = useState(kind === "video" ? String(projectId) : "");
  const [promotedProject, setPromotedProject] = useState<number | null>(null);
  const button = "rounded-lg border border-white/20 px-4 py-2 text-sm disabled:opacity-40";
  const field = "mt-1 w-full rounded-lg border border-white/15 bg-zinc-900 p-2 text-sm";
  const approvedImages = media.filter(item => item.approved && ["portrait", "visual"].includes(item.role) && item.mime.startsWith("image/"));
  const references = media.filter(item => item.role === "reference" && item.mime.startsWith("image/"));
  const supportsText = connection?.health.capabilities?.includes("text_to_image") === true;
  const supportsVton = connection?.health.capabilities?.includes("virtual_try_on") === true;
  const isVton = provider === "colab" && generationMode === "vton";
  const personImages = media.filter(item => item.mime.startsWith("image/") && (item.role === "reference" || (item.approved && ["portrait", "visual"].includes(item.role))));
  const garments = media.filter(item => item.role === "garment" && item.mime.startsWith("image/"));
  const hasPending = !!unconfirmedRequest || history.some(pending);
  async function loadHistory() {
    const rows = await studioRequest<ImageOperation[]>(`/studio/projects/${projectId}/operations`);
    setHistory(rows.filter(row => row.kind === "image"));
    setHistoryLoaded(true);
    if (rows.some(row => row.request_id === unconfirmedRequest)) setUnconfirmedRequest("");
  }
  useEffect(() => {
    if (kind === "legacy") return;
    let cancelled = false;
    void Promise.all([studioRequest<ImageOperation[]>(`/studio/projects/${projectId}/operations`),
      studioRequest<ColabImageConnection>("/studio/connections/colab-image")]).then(([rows, state]) => {
      if (!cancelled) {
        const images = rows.filter(row => row.kind === "image");
        setHistory(images); setHistoryLoaded(true); setConnection(state);
        const active = images.find(pending);
        if (active?.input_json) {
          try {
            const saved = JSON.parse(active.input_json);
            if (["colab", "gemini"].includes(saved.provider)) setProvider(saved.provider);
            if (["reference", "text", "vton"].includes(saved.generation_mode)) setGenerationMode(saved.generation_mode);
            if (["human", "pet"].includes(saved.subject_type)) setSubject(saved.subject_type);
            if (typeof saved.prompt === "string") setPrompt(saved.prompt);
            if (typeof saved.seed === "number") setSeed(saved.seed);
            if (typeof saved.reference_strength === "number") setStrength(saved.reference_strength);
            if (typeof saved.steps === "number") setSteps(saved.steps);
            if (typeof saved.guidance_scale === "number") setGuidance(saved.guidance_scale);
            if (saved.scene_id) setScene(String(saved.scene_id));
            if (Array.isArray(saved.reference_media_ids)) setReferenceIds(saved.reference_media_ids);
            if (saved.person_media_id) setPersonId(String(saved.person_media_id));
            if (saved.garment_media_id) setGarmentId(String(saved.garment_media_id));
            if (["tops", "bottoms", "one-pieces"].includes(saved.garment_category)) setGarmentCategory(saved.garment_category);
          } catch { /* Older operation history may not contain generation settings. */ }
        }
      }
    }).catch(error => { if (!cancelled) setMessage(String(error)); });
    return () => { cancelled = true; };
  }, [projectId, kind]);
  async function act(path: string, body?: unknown) {
    setBusy(true); setMessage("");
    try {
      await studioRequest(path, "POST", body); await onChanged();
      setMessage("Đã hoàn tất. Xem tài nguyên bên dưới."); return true;
    } catch (error) { setMessage(String(error)); return false; } finally { setBusy(false); }
  }
  async function generate() {
    const requestId = crypto.randomUUID();
    setBusy(true); setMessage(""); setUnconfirmedRequest(requestId);
    try {
      const result = await studioRequest<ImageOperation>(`/studio/projects/${projectId}/generate-image`, "POST", {
        request_id: requestId, scene_id: kind === "video" ? Number(scene) : null, provider, subject_type: provider === "colab" && generationMode !== "reference" ? "human" : subject,
        prompt: isVton ? "" : prompt.trim(), ...(provider === "colab" ? { generation_mode: generationMode, ...(isVton ? { person_media_id: Number(personId), garment_media_id: Number(garmentId), garment_category: garmentCategory, garment_photo_type: "flat-lay" } : { reference_media_ids: generationMode === "text" ? [] : referenceIds }), seed, reference_strength: strength, steps, guidance_scale: guidance } : {}),
      });
      setHistory(previous => [result, ...previous.filter(row => row.request_id !== result.request_id)]);
      setUnconfirmedRequest(""); setMessage(result.error || statuses[result.status] || result.status);
      await onChanged();
    } catch (error) {
      const rejected = error instanceof Error && "status" in error && Number(error.status) >= 400 && Number(error.status) < 500;
      if (rejected) setUnconfirmedRequest("");
      setMessage(`${String(error)}${rejected ? "" : " Kiểm tra trạng thái lượt vừa gửi trước khi tạo lượt khác."}`);
    } finally { setBusy(false); }
  }
  async function refreshOperation(requestId: string) {
    setBusy(true); setMessage("");
    try {
      const result = await studioRequest<ImageOperation>(`/studio/projects/${projectId}/operations/${requestId}/refresh`, "POST");
      setHistory(previous => [result, ...previous.filter(row => row.request_id !== result.request_id)]);
      setUnconfirmedRequest(""); setMessage(result.error || statuses[result.status] || result.status);
      await onChanged();
    } catch (error) {
      if (error instanceof Error && "status" in error && Number(error.status) === 404) setUnconfirmedRequest("");
      setMessage(String(error));
    } finally { setBusy(false); }
  }
  async function checkWorker() {
    setBusy(true); setMessage("");
    try {
      setConnection(await studioRequest<ColabImageConnection>("/studio/connections/colab-image/check", "POST"));
      setMessage("Đã kiểm tra worker ảnh.");
    } catch (error) {
      setMessage(String(error));
      setConnection(await studioRequest<ColabImageConnection>("/studio/connections/colab-image").catch(() => null));
    } finally { setBusy(false); }
  }
  if (kind === "legacy") return <section className="space-y-3 rounded-xl border border-white/10 p-4"><h3 className="font-semibold">Dự án chưa phân loại</h3><p className="text-sm text-zinc-400">Mở Timeline để tiếp tục luồng cũ, hoặc xác nhận loại video bên trên để dùng xưởng sản xuất.</p><Link className={button} to={`/timeline/${projectId}`}>Timeline & Flow</Link></section>;
  return <section className="space-y-4 rounded-xl border border-white/10 p-4">
    <h3 className="font-semibold">Tạo và nhận tài nguyên</h3>
    <div className="flex flex-wrap gap-3"><Link className={button} to={`/connections?project=${projectId}`}>Tạo / tiếp tục lời đọc</Link><Link className={button} to={`/timeline/${projectId}`}>Timeline & Flow</Link><Link className={button} to="/studio-settings">Provider & thư viện</Link>{kind === "video" && <button className={button} disabled={busy} onClick={() => void act(`/studio/projects/${projectId}/collect-clips`)}>Nhận clip từ Timeline vào xưởng</button>}</div>
    <fieldset disabled={busy || hasPending || !historyLoaded} className="space-y-3 border-0 p-0">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">Provider tạo ảnh<select aria-label="Provider tạo ảnh" className={field} value={provider} onChange={event => setProvider(event.target.value as "gemini" | "colab")}><option value="gemini">Gemini ảnh</option><option value="colab">Colab tạo ảnh</option></select></label>
        <label className="block text-sm">Chủ thể<select aria-label="Chủ thể" className={field} value={provider === "colab" && generationMode !== "reference" ? "human" : subject} disabled={provider === "colab" && generationMode !== "reference"} onChange={event => setSubject(event.target.value as "human" | "pet")}><option value="human">Người</option><option value="pet">Thú cưng</option></select></label>
      </div>
      {provider === "colab" && <label className="block text-sm">Cách tạo ảnh<select aria-label="Cách tạo ảnh" className={field} value={generationMode} onChange={event => { setGenerationMode(event.target.value as "reference" | "text" | "vton"); setGuidance(event.target.value === "vton" ? 1.5 : 4.5); if (event.target.value !== "reference") setSubject("human"); }}><option value="reference">Giữ ngoại hình từ ảnh tham chiếu</option><option value="text">Nhân vật hư cấu từ mô tả</option><option value="vton">Thử trang phục shop lên người (VTON)</option></select></label>}
      {isVton && <div className="space-y-3 rounded-lg border border-emerald-400/20 p-3">
        <p className="text-sm text-zinc-300">Chọn ảnh người muốn giữ dáng và ảnh đúng sản phẩm của shop. VTON thay trang phục trên ảnh người; kết quả cần so sánh với sản phẩm trước khi dùng.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">Ảnh người<select aria-label="Ảnh người" className={field} value={personId} onChange={event => setPersonId(event.target.value)}><option value="">Chọn ảnh người</option>{personImages.map(item => <option key={item.id} value={item.id}>Ảnh người #{item.id}{item.approved ? " · Đã duyệt" : " · Tham chiếu"}</option>)}</select>{!personImages.length && <span className="text-xs text-amber-200">Nhập ảnh người ở phần ảnh tham chiếu bên dưới.</span>}</label>
          <label className="block text-sm">Ảnh trang phục shop<select aria-label="Ảnh trang phục shop" className={field} value={garmentId} onChange={event => setGarmentId(event.target.value)}><option value="">Chọn sản phẩm shop</option>{garments.map(item => <option key={item.id} value={item.id}>Trang phục #{item.id}</option>)}</select>{!garments.length && <span className="text-xs text-amber-200">Nhập ảnh trang phục shop ở bên dưới; ảnh này được lưu riêng với ảnh người.</span>}</label>
          <label className="block text-sm">Loại trang phục<select aria-label="Loại trang phục" className={field} value={garmentCategory} onChange={event => setGarmentCategory(event.target.value as typeof garmentCategory)}><option value="tops">Áo</option><option value="bottoms">Quần / chân váy</option><option value="one-pieces">Váy liền / đồ liền thân</option></select></label>
          <label className="block text-sm">Cách chụp sản phẩm<select aria-label="Cách chụp sản phẩm" className={field} value="flat-lay" disabled><option value="flat-lay">Trang phục trải phẳng, nền sạch</option><option value="model" disabled>Trang phục trên người mẫu — chưa hỗ trợ</option></select></label>
        </div>
        <p className="text-xs text-zinc-400">Chọn ảnh một trang phục trải phẳng trên nền sạch, thấy đầy đủ sản phẩm; không dùng ảnh ghép hoặc ảnh shop có người mẫu mặc đồ. Kết quả gốc 576 × 864px.</p>
        <div className="grid gap-3 sm:grid-cols-2">{[[personId, "Ảnh người gốc"], [garmentId, "Trang phục shop gốc"]].map(([id, label]) => id && <figure key={label}><img src={`/api/production/media/${id}`} alt={label} className="max-h-72 w-full object-contain" /><figcaption className="mt-1 text-center text-xs text-zinc-400">{label}</figcaption></figure>)}</div>
        <p className="text-xs text-zinc-400">Muốn giữ dáng thanh mảnh, hãy chọn ảnh người gốc có dáng đó. VTON dùng dáng từ ảnh người và trang phục từ ảnh shop. Ảnh thử đồ không xác nhận size hoặc độ vừa thực tế.</p>
      </div>}
      {isVton && !supportsVton && <p className="text-xs text-amber-200">Worker chưa hỗ trợ thử trang phục. Khởi động worker ở chế độ VTON rồi kiểm tra lại kết nối.</p>}
      {provider === "colab" && generationMode === "text" && <p className="text-xs text-zinc-400">Không dùng ảnh người thật; vẫn cần kiểm tra kết quả và giấy phép model trước sử dụng.</p>}
      {provider === "colab" && generationMode === "text" && !supportsText && <p className="text-xs text-amber-200">Worker chưa hỗ trợ tạo từ mô tả. Tải notebook / worker mới rồi kiểm tra lại kết nối.</p>}
      {kind === "video" && <label className="block text-sm">Cảnh cần tạo ảnh<select aria-label="Cảnh cần tạo ảnh" className={field} value={scene} onChange={event => setScene(event.target.value)}><option value="">Chọn cảnh</option>{scenes.map(item => <option key={item.id} value={item.id}>Cảnh {item.order + 1}</option>)}</select></label>}
      {provider === "colab" && generationMode === "reference" && <label className="block text-sm">Ảnh tham chiếu gửi tới Colab (chọn 1–3 ảnh)<select aria-label="Ảnh tham chiếu gửi tới Colab" multiple size={Math.min(4, Math.max(2, references.length))} className={field} value={referenceIds.map(String)} onChange={event => {
        const selected = Array.from(event.target.selectedOptions, option => Number(option.value));
        if (selected.length <= 3) setReferenceIds(selected); else setMessage("Chỉ chọn tối đa 3 ảnh tham chiếu.");
      }}>{references.map(item => <option key={item.id} value={item.id}>Ảnh tham chiếu #{item.id}</option>)}</select>{!references.length && <span className="text-xs text-amber-200">Nhập ảnh tham chiếu của người / thú cưng ở bên dưới trước khi tạo.</span>}</label>}
      {!isVton && <><label className="block text-sm">Mô tả bổ sung cho ảnh<textarea className={`${field} min-h-24`} maxLength={10000} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder={provider === "colab" && generationMode === "text" ? "Người trưởng thành hư cấu, mắt nâu, áo sơ mi cotton, ánh sáng cửa sổ dịu, da tự nhiên." : "Ảnh chụp tự nhiên, ánh sáng cửa sổ dịu, giữ chất liệu da / bộ lông và đặc điểm của ảnh gốc."} /></label>
      <p className="text-xs text-zinc-400">Để trống để dùng brief và prompt của cảnh. {provider === "colab" && generationMode === "text" ? "Lượt này chỉ dùng mô tả, không gửi ảnh trong dự án." : "Ảnh tham chiếu đã nhập trong dự án sẽ được gửi kèm."} Mô tả vóc dáng / vòng ngực chỉ hướng dẫn mô hình, không phải tham số số đo cơ thể. Mô tả ánh sáng và chất liệu tự nhiên; tránh yêu cầu làm mịn da quá mức.</p></>}
      {provider === "colab" && <details><summary className="cursor-pointer text-sm">Tinh chỉnh lượt tạo ảnh</summary><div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-sm">Seed<input className={field} type="number" min={0} max={4294967295} step={1} value={seed} onChange={event => setSeed(Number(event.target.value))} /></label>
        {generationMode === "reference" && <label className="text-sm">Mức giữ ảnh tham chiếu: {strength.toFixed(2)}<input className="mt-3 w-full" type="range" min={0} max={1} step={0.05} value={strength} onChange={event => setStrength(Number(event.target.value))} /></label>}
        <label className="text-sm">Số bước<input className={field} type="number" min={10} max={50} step={1} value={steps} onChange={event => setSteps(Number(event.target.value))} /></label>
        <label className="text-sm">{isVton ? "Mức bám trang phục" : "Mức bám mô tả"}<input className={field} type="number" min={1} max={12} step={0.5} value={guidance} onChange={event => setGuidance(Number(event.target.value))} /></label>
      </div>{generationMode === "reference" && <p className="mt-3 text-xs text-zinc-400">Giảm mức giữ ảnh nếu nền hoặc khung hình gốc lấn át mô tả. Tăng để giữ ngoại hình sát hơn, nhưng có thể sao chép cả trang phục và nền.</p>}</details>}
    </fieldset>
    {provider === "colab" ? <div className="space-y-2"><p className="text-sm">{connection?.state === "ready" ? "Worker ảnh sẵn sàng" : "Worker ảnh chưa sẵn sàng"}{connection?.health.model_revision && ` · ${connection.health.model_revision}`}</p><button className={button} disabled={busy || !connection?.configured} onClick={() => void checkWorker()}>Kiểm tra worker ảnh</button>{!connection?.configured && <Link className="ml-3 text-emerald-300 underline" to="/studio-settings">Kết nối Colab ảnh</Link>}<p className="text-xs text-zinc-400">Lượt tạo chạy trên Colab. Bấm kiểm tra kết quả để nhận ảnh của lượt đã gửi; thao tác này không tạo ảnh mới.</p></div> : <p className="text-xs text-zinc-400">Gemini dùng quota / billing đã cấu hình. Kết quả cần xem và duyệt trước khi sử dụng.</p>}
    <button className={button} disabled={busy || hasPending || !historyLoaded || (kind === "video" && !scene) || (provider === "colab" && (connection?.state !== "ready" || (generationMode === "text" && !supportsText) || (isVton && (!supportsVton || !personImages.some(item => item.id === Number(personId)) || !garments.some(item => item.id === Number(garmentId)) || personId === garmentId)) || (generationMode === "reference" && (!referenceIds.length || !referenceIds.every(id => references.some(item => item.id === id)))) || !Number.isInteger(seed) || seed < 0 || seed > 4294967295 || !Number.isInteger(steps) || steps < 10 || steps > 50 || guidance < 1 || guidance > 12))} onClick={() => void generate()}>{busy ? "Đang xử lý…" : "Tạo ảnh"}</button>
    {hasPending && <p className="text-sm text-amber-200">Lượt đã gửi chưa có kết quả cuối. Kiểm tra lượt này trước khi tạo ảnh khác.</p>}
    <div className="space-y-2"><button className={button} disabled={busy} onClick={() => void loadHistory().catch(error => setMessage(String(error)))}>Tải lại lịch sử tạo ảnh</button>
      {unconfirmedRequest && <p className="text-sm">Lượt {unconfirmedRequest.slice(0, 8)} chưa xác nhận.{provider === "colab" ? <button className={`${button} ml-2`} disabled={busy} onClick={() => void refreshOperation(unconfirmedRequest)}>Kiểm tra kết quả (không tạo lại)</button> : " Tải lại lịch sử để kiểm tra lượt đã gửi."}</p>}
      <ul className="space-y-2 text-sm">{history.map(operation => <li key={operation.request_id}>{operation.request_id.slice(0, 8)} · {statuses[operation.status] || operation.status} {operation.error}{pending(operation) && colabOperation(operation) && <button className={`${button} ml-2`} disabled={busy} onClick={() => void refreshOperation(operation.request_id)}>Kiểm tra kết quả (không tạo lại)</button>}</li>)}</ul>
    </div>
    <div className="space-y-3 border-t border-white/10 pt-4"><h4 className="font-medium">Dùng ảnh đã duyệt làm tham chiếu video</h4><p className="text-xs text-zinc-400">Xem và duyệt ảnh ở bên dưới trước. Ảnh sẽ được sao chép vào dự án nhận; ảnh gốc vẫn giữ nguyên.</p>
      <label className="block text-sm">Ảnh đã duyệt<select aria-label="Ảnh đã duyệt" className={field} value={sourceImage} disabled={busy} onChange={event => setSourceImage(event.target.value)}><option value="">Chọn ảnh đã duyệt</option>{approvedImages.map(item => <option key={item.id} value={item.id}>Ảnh #{item.id}</option>)}</select></label>
      <label className="block text-sm">ID dự án video nhận ảnh<input className={field} type="number" min={1} step={1} value={targetProject} disabled={busy} onChange={event => setTargetProject(event.target.value)} /></label>
      <button className={button} disabled={busy || !approvedImages.some(item => item.id === Number(sourceImage)) || !Number.isSafeInteger(Number(targetProject)) || Number(targetProject) < 1} onClick={() => void act(`/studio/projects/${Number(targetProject)}/references`, { media_id: Number(sourceImage) }).then(ok => { if (ok) setPromotedProject(Number(targetProject)); })}>Dùng làm ảnh tham chiếu</button>
      {promotedProject && <Link className="ml-3 text-emerald-300 underline" to={`/production?project=${promotedProject}`}>Mở dự án nhận ảnh</Link>}
    </div>
    <p role="status" className="text-sm text-amber-200">{message}</p>
  </section>;
}
