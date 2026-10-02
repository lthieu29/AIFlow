import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import TrainingControl from "../components/TrainingControl";
import { studioRequest } from "./StudioSettings";

const field = "mt-1 w-full rounded-lg border border-white/15 bg-zinc-900 p-3 text-sm";
const button = "rounded-lg border border-white/20 px-4 py-2 text-sm hover:bg-white/10 disabled:opacity-40";
const panel = "space-y-4 rounded-xl border border-white/10 bg-zinc-900/40 p-5";
type Media = { id: string; key: string; size: number; group: string };
type Scan = { scan_id: string; files: Media[]; examined: number; expires_at: number };
const size = (bytes: number) => `${(bytes / 1024 ** 2).toFixed(1)} MiB`;

export default function VoiceTraining() {
  const [source, setSource] = useState({ account_id: "", jurisdiction: "default", bucket: "", prefix: "", access_key_id: "", secret_access_key: "" });
  const [scan, setScan] = useState<Scan | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [group, setGroup] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [voice, setVoice] = useState("");
  const [language, setLanguage] = useState("vi");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [exported, setExported] = useState(false);
  const [remoteJob, setRemoteJob] = useState("");
  const groups = useMemo(() => [...new Set(scan?.files.map(f => f.group) ?? [])], [scan]);
  const visible = useMemo(() => (scan?.files ?? []).filter(f => (!group || f.group === group) && f.key.toLowerCase().includes(search.toLowerCase())), [scan, group, search]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const chosen = scan?.files.filter(f => selectedSet.has(f.id)) ?? [];

  function changeSource(key: keyof typeof source, value: string) {
    setSource(s => ({ ...s, [key]: value }));
    setScan(null); setSelected([]); setConfirmed(false); setExported(false);
  }
  function choose(ids: string[]) { setSelected(ids); setConfirmed(false); setExported(false); }
  async function post(path: string, body: unknown) {
    const response = await fetch(`/api/voice-training/${path}`, { method: "POST", headers: { "Content-Type": "application/json", "X-AIFlow-Client": "1" }, body: JSON.stringify(body) });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : "Kiểm tra các trường nhập rồi thử lại.");
    }
    return response;
  }
  async function scanR2() {
    setBusy("scan"); setError(""); setScan(null); choose([]); setGroup(""); setSearch(""); setPage(0);
    try {
      setScan(await (await post("scan", source)).json());
      setSource(s => ({ ...s, access_key_id: "", secret_access_key: "" }));
    } catch (e) { setError(e instanceof Error ? e.message : "Không quét được R2."); }
    finally { setBusy(""); }
  }
  async function exportBundle() {
    setBusy("export"); setError("");
    try {
      const response = await post("bundle", { scan_id: scan?.scan_id, file_ids: selected, voice_name: voice, language, same_speaker_confirmed: confirmed });
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a"); a.href = url; a.download = "aiflow-selected-voice.zip"; a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000); setExported(true);
    } catch (e) { setError(e instanceof Error ? e.message : "Không tạo được gói Colab."); }
    finally { setBusy(""); }
  }

  return <main className="mx-auto max-w-6xl space-y-6 px-4 py-8">
    <header><p className="text-sm text-emerald-300">Giọng riêng · Fine-tune trên Colab</p><h1 className="mt-2 text-3xl font-semibold">Bạn muốn huấn luyện giọng nào?</h1><p className="mt-3 max-w-3xl text-zinc-400">Quét danh sách trước, chọn file sau. Chỉ Colab tải và xử lý các file bạn chọn; máy này không chạy model AI.</p></header>
    <TrainingControl incomingJob={remoteJob} />
    <ol className="flex flex-wrap gap-4 text-sm text-zinc-400"><li className={!scan ? "text-emerald-300" : ""}>1. Quét R2</li><li className={scan && !exported ? "text-emerald-300" : ""}>2. Chọn giọng và dữ liệu</li><li className={exported ? "text-emerald-300" : ""}>3. Tải / duyệt / huấn luyện trên Colab</li></ol>
    {error && <p role="alert" className="rounded-lg border border-rose-400/30 p-4 text-rose-300">{error}</p>}
    <form className={panel} onSubmit={e => { e.preventDefault(); void scanR2(); }}>
      <h2 className="text-xl font-semibold">1. Nguồn R2</h2>
      <p className="text-sm text-zinc-400">Dùng S3 credentials có quyền Object Read cho bucket. Không cần bật public access. Khóa không lưu xuống ổ đĩa; quét xong sẽ xóa khỏi ô nhập.</p>
      <fieldset disabled={!!busy} className="grid gap-4 sm:grid-cols-2">
        <label>Account ID<input required className={field} value={source.account_id} onChange={e => changeSource("account_id", e.target.value.trim())} pattern="[a-fA-F0-9]{32}" /></label>
        <label>Bucket<input required className={field} value={source.bucket} onChange={e => changeSource("bucket", e.target.value.trim())} /></label>
        <label>Prefix (để trống để quét cả bucket)<input className={field} value={source.prefix} onChange={e => changeSource("prefix", e.target.value)} placeholder="voices/ten-nguoi/" /></label>
        <label>Jurisdiction<select className={field} value={source.jurisdiction} onChange={e => changeSource("jurisdiction", e.target.value)}><option value="default">Mặc định</option><option value="eu">EU</option><option value="fedramp">FedRAMP</option></select></label>
        <label>Access Key ID<input required type="password" autoComplete="off" className={field} value={source.access_key_id} onChange={e => changeSource("access_key_id", e.target.value)} /></label>
        <label>Secret Access Key<input required type="password" autoComplete="off" className={field} value={source.secret_access_key} onChange={e => changeSource("secret_access_key", e.target.value)} /></label>
      </fieldset>
      <button disabled={!!busy} className={button}>{busy === "scan" ? "Đang quét tất cả các trang danh sách…" : "Quét danh sách • chưa tải media"}</button>
    </form>
    {scan && <section className={panel} aria-busy={!!busy}>
      <h2 className="text-xl font-semibold">2. Chọn dữ liệu của một giọng</h2>
      <p role="status" className="text-sm text-zinc-400">Đã xem {scan.examined} object · {scan.files.length} file media · chưa tải file nào. Danh sách có hiệu lực 1 giờ.</p>
      <p className="text-sm text-amber-200">Thư mục chỉ giúp phân nhóm. Chưa nghe audio nên hệ thống chưa biết bên trong có ai nói. Chọn file của cùng một người; tránh nhạc nền và hội thoại nhiều người.</p>
      {!scan.files.length ? <p>Không có file media hợp lệ. Kiểm tra prefix rồi quét lại.</p> : <>
        <div className="grid gap-4 sm:grid-cols-2"><label>Nhóm thư mục<select className={field} value={group} onChange={e => { setGroup(e.target.value); setPage(0); }}><option value="">Tất cả thư mục</option>{groups.map(g => <option key={g}>{g}</option>)}</select></label><label>Tìm tên file<input className={field} value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} /></label></div>
        <div className="flex flex-wrap gap-3"><button disabled={!!busy || !visible.length} className={button} onClick={() => choose([...new Set([...selected, ...visible.map(f => f.id)])])}>Chọn {visible.length} file theo bộ lọc</button><button disabled={!!busy || !selected.length} className={button} onClick={() => choose([])}>Bỏ chọn tất cả ({selected.length})</button></div>
        <div className="max-h-96 overflow-auto rounded-lg border border-white/10">{visible.slice(page * 100, (page + 1) * 100).map(file => <label key={file.id} className="flex items-start gap-3 border-b border-white/5 p-3 text-sm"><input type="checkbox" disabled={!!busy} checked={selectedSet.has(file.id)} onChange={e => choose(e.target.checked ? [...selected, file.id] : selected.filter(id => id !== file.id))} /><span className="min-w-0 flex-1 break-all">{file.key}</span><span className="whitespace-nowrap text-zinc-400">{size(file.size)}</span></label>)}{!visible.length && <p className="p-4">Không có file khớp bộ lọc.</p>}</div>
        <div className="flex items-center gap-3 text-sm"><button className={button} disabled={page === 0} onClick={() => setPage(page - 1)}>Trước</button><span>Trang {page + 1} / {Math.max(1, Math.ceil(visible.length / 100))}</span><button className={button} disabled={(page + 1) * 100 >= visible.length} onClick={() => setPage(page + 1)}>Sau</button></div>
        <fieldset disabled={!!busy} className="space-y-4"><div className="grid gap-4 sm:grid-cols-2"><label>Tên giọng<input maxLength={80} className={field} value={voice} onChange={e => { setVoice(e.target.value); setExported(false); }} placeholder="Giọng kể chuyện kênh A" /></label><label>Ngôn ngữ dữ liệu<select className={field} value={language} onChange={e => { setLanguage(e.target.value); setExported(false); }}><option value="vi">Tiếng Việt</option><option value="en">Tiếng Anh</option></select></label></div>
        <p>Đã chọn <strong>{chosen.length} file · {size(chosen.reduce((sum, f) => sum + f.size, 0))}</strong> (kể cả file ngoài bộ lọc hiện tại).</p>
        <label className="flex gap-3 text-sm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Tôi xác nhận đây là dữ liệu của cùng một người nói, là giọng của tôi hoặc tôi được phép huấn luyện giọng này.</label>
        <button className={button} disabled={!selected.length || selected.length > 5000 || !voice.trim() || !confirmed} onClick={() => void exportBundle()}>{busy === "export" ? "Đang đóng gói…" : "Tải gói notebook để làm thủ công"}</button>
        <button className={`${button} ml-2`} disabled={!selected.length || selected.length > 5000 || !voice.trim() || !confirmed} onClick={() => { setBusy("send"); setError(""); void studioRequest<{ job_id: string }>("/training-control/selections", "POST", { scan_id: scan.scan_id, file_ids: selected, voice_name: voice, language, same_speaker_confirmed: confirmed }).then(result => { setRemoteJob(result.job_id); setExported(true); }).catch(e => setError(String(e))).finally(() => setBusy("")); }}>Gửi lựa chọn sang Colab • chưa tải media</button></fieldset>
      </>}
    </section>}
    <section className={panel}><h2 className="text-xl font-semibold">3. Tiếp tục trên Colab</h2>{exported && <p role="status" className="text-emerald-300">Đã tạo gói theo lựa chọn. Media chưa được tải, GPU chưa được bật.</p>}<ol className="list-decimal space-y-2 pl-5 text-sm text-zinc-300"><li>Giải nén ZIP, mở <code>finetune_r2.ipynb</code> trên Colab và chọn GPU. Upload chính ZIP đó ở ô đầu tiên.</li><li>Tạo Colab Secrets <code>R2_ACCESS_KEY_ID</code> và <code>R2_SECRET_ACCESS_KEY</code>, cho notebook quyền đọc. Chạy ô “Tải đúng file đã chọn”.</li><li>Chạy tạo dataset, nghe các đoạn và sửa transcript trong trình duyệt notebook. Bấm duyệt dataset rồi mới chạy fine-tune.</li><li>Nghe mẫu sau huấn luyện, duyệt giọng, bật API. My Drive lưu dataset, adapter, model và thông tin giọng.</li><li>Dán URL / token vào <Link className="text-emerald-300 underline" to="/connections">Colab & audio</Link>, kiểm tra và lưu để danh sách giọng cập nhật.</li></ol><p className="text-sm text-zinc-400">Lần sau chỉ load giọng đã duyệt từ Drive. Có thể đổi giọng trong phiên khi worker rảnh. Nếu train bị ngắt: dùng Tiếp tục checkpoint trên bản có checkpoint đầy đủ; giữ nguyên dataset và môi trường.</p></section>
  </main>;
}
