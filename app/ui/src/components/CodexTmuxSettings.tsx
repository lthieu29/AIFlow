import { useEffect, useState } from "react";
type Settings = { distro: string; confirmed: boolean; ready: boolean; timeout_seconds: number; message: string };
const field = "w-full rounded-lg border border-white/15 bg-zinc-900 p-3 text-sm";
const button = "rounded-lg border border-white/20 px-4 py-2 text-sm disabled:opacity-40";
export default function CodexTmuxSettings() {
  const [settings, setSettings] = useState<Settings>({ distro: "Ubuntu", confirmed: false, ready: false, timeout_seconds: 1200, message: "" });
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { let active = true; fetch("/api/scripts/connection").then(r => { if (!r.ok) throw new Error("Không đọc được cấu hình."); return r.json(); }).then(s => { if (active) setSettings(s.codex); }).catch(e => { if (active) setError(String(e)); }); return () => { active = false; }; }, []);
  async function save(confirmed: boolean) {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/scripts/codex/connection", { method: "PUT", headers: { "Content-Type": "application/json", "X-AIFlow-Client": "1" }, body: JSON.stringify({ distro: settings.distro, timeout_seconds: settings.timeout_seconds, confirmed }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Kiểm tra distro và thời gian chờ.");
      setSettings(data);
    } catch (e) { setError(String(e)); setSettings(s => ({ ...s, ready: false })); }
    finally { setBusy(false); }
  }
  return <section className="space-y-4 rounded-xl border border-white/10 p-5">
    <h2 className="text-xl">Codex qua tmux / WSL</h2>
    <p className="text-sm text-zinc-400">Chạy CAO trong Ubuntu và đăng nhập Codex bằng ChatGPT. Không cần nhập API key. Mỗi lượt dùng một phiên riêng và trả kết quả về xưởng kịch bản.</p>
    <form className="space-y-3" onSubmit={e => { e.preventDefault(); void save(settings.confirmed); }}>
      <label className="block">Tên distro WSL<input required className={field} value={settings.distro} onChange={e => setSettings({ ...settings, distro: e.target.value, ready: false })} /></label>
      <label className="block">Thời gian tối đa mỗi lượt (giây)<input type="number" min={120} max={3600} className={field} value={settings.timeout_seconds} onChange={e => setSettings({ ...settings, timeout_seconds: Number(e.target.value) })} /></label>
      <label className="flex items-start gap-3 text-sm"><input className="mt-1" type="checkbox" checked={settings.confirmed} onChange={e => setSettings({ ...settings, confirmed: e.target.checked })} />Tôi đã kiểm tra tài khoản ChatGPT, không bật tự nạp và không có credits bổ sung khả dụng nếu muốn chỉ dùng hạn mức subscription. Tôi hiểu tmux không thay đổi cách tính credits; AIFlow chỉ kiểm tra được kiểu đăng nhập.</label>
      <div className="flex flex-wrap gap-2"><button className={button} disabled={busy || !settings.confirmed}>{busy ? "Đang kiểm tra WSL/CAO…" : "Kiểm tra & bật cho phiên AIFlow này"}</button><button type="button" className={button} disabled={busy} onClick={() => void save(false)}>Ngừng nhận tác vụ mới</button></div>
    </form>
    <p role="status" className="text-sm">{settings.ready ? "Đã kiểm tra kết nối" : "Chưa bật"} · {settings.message}</p>
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    <details className="text-sm text-zinc-400"><summary className="cursor-pointer">Cài đặt và mở phiên</summary><div className="mt-3 space-y-2">
      <p>Nếu chỉ có docker-desktop: cài Ubuntu bằng <code>wsl --install -d Ubuntu</code>, mở Ubuntu và tạo user.</p>
      <p>Cài Node.js LTS và Codex CLI trong Ubuntu, sau đó:</p>
      <pre className="overflow-x-auto rounded bg-black/30 p-3">{`cd /mnt/d/Project/AIFlow/app/codex_tmux\nbash setup.sh\ncodex login\npython3 bridge.py serve`}</pre>
      <p>Giữ cửa sổ CAO đang chạy. Đăng nhập bằng ChatGPT, không chọn API key. Nếu dự án nằm nơi khác, thay đường dẫn tương ứng. Restart AIFlow cần kiểm tra/bật lại; các lượt cũ vẫn đồng bộ được.</p>
    </div></details>
  </section>;
}
