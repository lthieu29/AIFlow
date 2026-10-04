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
const mediaFormats = ".mp3,.wav,.flac,.m4a,.ogg,.aac,.opus,.mp4,.mov,.mkv,.webm";
const mediaExtensions = new Set(mediaFormats.split(","));

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
  const [localFiles, setLocalFiles] = useState<File[]>([]);
  const [localName, setLocalName] = useState("");
  const [localConfirmed, setLocalConfirmed] = useState(false);
  const [localRequest, setLocalRequest] = useState(() => crypto.randomUUID());
  const [localNotice, setLocalNotice] = useState("");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [youtubeName, setYoutubeName] = useState("");
  const [youtubeConfirmed, setYoutubeConfirmed] = useState(false);
  const [youtubeRequest, setYoutubeRequest] = useState(() => crypto.randomUUID());
  const [youtubeNotice, setYoutubeNotice] = useState("");
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

  async function uploadLocal() {
    setBusy("local"); setError(""); setLocalNotice("");
    try {
      async function request(path: string, options: RequestInit = {}) {
        const response = await fetch(`/api/training-control/${path}`, { ...options, headers: { "X-AIFlow-Client": "1", ...options.headers } });
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Không gửi được media. Gửi lại cùng lựa chọn để tiếp tục.");
        return result;
      }
      const metadata = { voice_name: localName.trim(), language: "vi",
        files: localFiles.map(file => ({ name: file.name, size: file.size, last_modified: file.lastModified })).sort((a, b) => a.name.localeCompare(b.name)) };
      const identity = JSON.stringify(metadata);
      let requestId = localRequest;
      // Retain only metadata, so reselecting the same files after a refresh resumes Drive offsets.
      try {
        const previous = JSON.parse(localStorage.getItem("aiflow-local-media-selection") ?? "null");
        if (previous?.identity === identity && typeof previous.request_id === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(previous.request_id)) requestId = previous.request_id;
        localStorage.setItem("aiflow-local-media-selection", JSON.stringify({ identity, request_id: requestId }));
      } catch { /* Upload still resumes within this page when browser storage is unavailable. */ }
      setLocalRequest(requestId);
      const selection = await request("local-media", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        ...metadata, request_id: requestId, same_speaker_confirmed: localConfirmed,
      }) });
      if (selection.chunk_bytes !== 8 * 1024 ** 2) throw new Error("Worker trả giới hạn upload không tương thích.");
      let completed = 0;
      for (const file of localFiles) {
        const item = selection.files.find((item: { key: string }) => item.key === file.name);
        if (!item) throw new Error("Worker chưa khóa đúng danh sách media.");
        const path = `local-media/${selection.job_id}/sources/${item.id}`;
        let status = await request(path);
        if (!Number.isSafeInteger(status.offset) || status.offset < 0 || status.offset > file.size) throw new Error("Checkpoint upload không hợp lệ.");
        if (!status.stored && status.offset === file.size) status.offset = Math.max(0, file.size - selection.chunk_bytes);
        while (!status.stored) {
          const offset = status.offset;
          if (offset >= file.size) throw new Error("Worker chưa xác nhận checksum cuối file. Kiểm tra Colab rồi gửi lại.");
          setLocalNotice(`File ${completed + 1}/${localFiles.length}: ${file.name} · ${size(offset)}/${size(file.size)}. Gửi lại cùng lựa chọn nếu mạng ngắt.`);
          const form = new FormData();
          form.append("offset", String(offset));
          form.append("file", file.slice(offset, Math.min(offset + selection.chunk_bytes, file.size)), file.name);
          status = await request(path, { method: "POST", body: form });
          if (!Number.isSafeInteger(status.offset) || status.offset <= offset || status.offset > file.size) throw new Error("Worker chưa xác nhận phần upload; gửi lại cùng lựa chọn.");
        }
        if (status.offset !== file.size || !/^[a-f0-9]{64}$/.test(status.checksum)) throw new Error("Worker chưa xác nhận checksum cuối file.");
        completed += 1;
      }
      setRemoteJob(selection.job_id);
      try {
        if (JSON.parse(localStorage.getItem("aiflow-local-media-selection") ?? "null")?.request_id === requestId) localStorage.removeItem("aiflow-local-media-selection");
      } catch { /* Completed jobs remain selectable from the Drive job list. */ }
      setLocalNotice(`Đã lưu ${completed} file media đúng checksum trên Drive. Chưa chép lời hoặc train; chọn bước 2 ở điều khiển bên trên để chuẩn hóa mono 24 kHz và tách đoạn.`);
    } catch (error) { setError(error instanceof Error ? error.message : "Không gửi được media local."); }
    finally { setBusy(""); }
  }

  async function importYoutube() {
    setBusy("youtube"); setError(""); setYoutubeNotice("");
    try {
      const health = await studioRequest<{ busy: boolean; youtube_source?: string }>("/training-control/remote/health");
      if (health.youtube_source !== "single-video-v1") throw new Error("Colab chưa hỗ trợ nhập YouTube. Tải gói worker mới và chạy lại notebook điều khiển.");
      if (health.busy) throw new Error("Colab đang xử lý tác vụ khác. Chờ tác vụ đó hoàn tất rồi gửi URL.");
      const result = await studioRequest<{ job_id: string; source_url: string }>("/training-control/youtube", "POST", {
        request_id: youtubeRequest, voice_name: youtubeName.trim(), language: "vi", same_speaker_confirmed: youtubeConfirmed, url: youtubeUrl.trim(),
      });
      setRemoteJob(result.job_id);
      setYoutubeNotice(`Đã lưu nguồn ${result.source_url} trên Drive. Đang gửi yêu cầu tải audio tới Colab…`);
      await studioRequest(`/training-control/remote/jobs/${result.job_id}/actions`, "POST", { request_id: youtubeRequest, kind: "download" });
      setYoutubeNotice("Đã gửi tác vụ tải audio trên Colab. Xem trạng thái ở điều khiển bên trên; khi tải xong, bấm bước 2 để tách đoạn / chép lời, rồi kiểm tra và duyệt dataset trước khi train.");
    } catch (e) { setError(e instanceof Error ? e.message : "Không gửi được URL YouTube. Kiểm tra kết nối Colab rồi thử lại."); }
    finally { setBusy(""); }
  }

  function changeYoutube() { setYoutubeRequest(crypto.randomUUID()); setYoutubeConfirmed(false); setYoutubeNotice(""); }

  function chooseLocal(files: FileList | null) {
    setLocalFiles(Array.from(files ?? [])); setLocalRequest(crypto.randomUUID()); setLocalConfirmed(false); setLocalNotice("");
  }
  const localInvalid = localFiles.some(file => !mediaExtensions.has(file.name.slice(file.name.lastIndexOf(".")).toLowerCase())
    || file.size === 0 || file.size > 2 * 1024 ** 3) || new Set(localFiles.map(file => file.name)).size !== localFiles.length;

  return <main className="mx-auto max-w-6xl space-y-6 px-4 py-8">
    <header><p className="text-sm text-emerald-300">Giọng riêng · Fine-tune trên Colab</p><h1 className="mt-2 text-3xl font-semibold">Bạn muốn huấn luyện giọng nào?</h1><p className="mt-3 max-w-3xl text-zinc-400">Nhập URL YouTube, chọn audio/video trên máy hoặc quét R2 rồi chọn file. Colab lấy âm thanh, chuẩn hóa và chép lời; bạn kiểm tra dữ liệu và duyệt trước khi bấm huấn luyện. Máy này không chạy model AI.</p></header>
    <TrainingControl incomingJob={remoteJob} />
    {error && <p role="alert" className="rounded-lg border border-rose-400/30 p-4 text-rose-300">{error}</p>}
    <form className={panel} onSubmit={event => { event.preventDefault(); void importYoutube(); }}>
      <h2 className="text-xl font-semibold">Audio từ YouTube · Tiếng Việt</h2>
      <p className="text-sm text-zinc-400">Kết nối Colab rồi nhập URL của một video. Colab tải audio và giữ URL nguồn cùng thông tin file trên Drive. Tối đa 3 giờ/video, 512 MiB audio và 10 phút cho lượt tải. Video cần đăng nhập hoặc bị YouTube chặn tải sẽ báo lỗi.</p>
      <fieldset disabled={!!busy} className="space-y-3">
        <label className="block">Tên giọng<input required className={field} maxLength={80} value={youtubeName} placeholder="Giọng kể chuyện" onChange={event => { setYoutubeName(event.target.value); changeYoutube(); }} /></label>
        <label className="block">URL video YouTube<input required type="url" className={field} maxLength={2048} value={youtubeUrl} placeholder="https://www.youtube.com/watch?v=iaPiJZeJwQk" onChange={event => { setYoutubeUrl(event.target.value); changeYoutube(); }} /></label>
        <label className="flex gap-3 text-sm"><input type="checkbox" checked={youtubeConfirmed} onChange={event => setYoutubeConfirmed(event.target.checked)} />Đây là giọng của tôi hoặc tôi được phép huấn luyện, và tôi đã chọn video chứa cùng một người nói.</label>
        <button className={button} disabled={!youtubeName.trim() || !youtubeUrl.trim() || !youtubeConfirmed}>{busy === "youtube" ? "Đang gửi URL tới Colab…" : "Gửi URL & tải audio trên Colab"}</button>
      </fieldset>
      {youtubeNotice && <p role="status" className="break-words text-sm text-emerald-300">{youtubeNotice}</p>}
    </form>
    <section className={panel}>
      <h2 className="text-xl font-semibold">Audio / video trên máy · Tiếng Việt</h2>
      <p className="text-sm text-zinc-400">Kết nối Colab rồi chọn file hoặc thư mục. Nhận MP3, WAV, FLAC, M4A, OGG, AAC, OPUS, MP4, MOV, MKV, WEBM với sample rate khác nhau. Colab kiểm tra có âm thanh rồi chuẩn hóa mono 24 kHz PCM trước khi chép lời; nguồn gốc được giữ trên Drive.</p>
      <fieldset disabled={!!busy} className="space-y-3">
        <label className="block">Tên giọng<input className={field} maxLength={80} value={localName} placeholder="Thuần Podcast" onChange={event => { setLocalName(event.target.value); setLocalRequest(crypto.randomUUID()); setLocalNotice(""); }} /></label>
        <label className="block">Chọn các file audio / video<input className={field} type="file" multiple accept={mediaFormats} onChange={event => chooseLocal(event.target.files)} /></label>
        <label className="block">Hoặc chọn thư mục<input className={field} type="file" multiple accept={mediaFormats} {...{ webkitdirectory: "" }} onChange={event => chooseLocal(event.target.files)} /></label>
        <p className="text-sm">Đã chọn {localFiles.length} file · {size(localFiles.reduce((total, file) => total + file.size, 0))}. Tối đa 2 GiB/file, 20 GiB/lượt, 5000 file. Upload từng phần 8 MiB; nếu tải lại trang, chọn lại đúng các file và tên giọng để tiếp tục. File dài được xử lý theo từng đoạn trên Colab.</p>
        {localInvalid && <p role="alert" className="text-sm text-rose-300">Có file rỗng, vượt 2 GiB, sai định dạng hoặc trùng tên. Chọn lại các file hợp lệ, mỗi file một tên riêng.</p>}
        <label className="flex gap-3 text-sm"><input type="checkbox" checked={localConfirmed} onChange={event => setLocalConfirmed(event.target.checked)} />Đây là giọng của tôi hoặc tôi được phép huấn luyện, và các file chứa cùng một người nói.</label>
        <button className={button} disabled={!localName.trim() || !localConfirmed || !localFiles.length || localFiles.length > 5000 || localInvalid || localFiles.reduce((sum, file) => sum + file.size, 0) > 20 * 1024 ** 3} onClick={() => void uploadLocal()}>{busy === "local" ? "Đang upload từng phần và xác nhận checksum…" : "Gửi media local sang Colab / Drive"}</button>
      </fieldset>
      {localNotice && <p role="status" className="text-sm text-emerald-300">{localNotice}</p>}
    </section>
    <ol className="flex flex-wrap gap-4 text-sm text-zinc-400"><li className={!scan ? "text-emerald-300" : ""}>1. Quét R2</li><li className={scan && !exported ? "text-emerald-300" : ""}>2. Chọn giọng và dữ liệu</li><li className={exported ? "text-emerald-300" : ""}>3. Tải / duyệt / huấn luyện trên Colab</li></ol>
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
