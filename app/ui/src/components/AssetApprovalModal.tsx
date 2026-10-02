/**
 * AssetApprovalModal — manual G2 quality gate.
 *
 * The pipeline pauses at G2 to let the user approve the reference assets
 * (character / product / location) before scene generation starts.  This
 * modal opens whenever the SSE stream signals a checking G2 gate, shows
 * the project's current asset list, and POSTs to /gates/{id}/approve or
 * /gates/{id}/override.
 */

import { useEffect, useState } from "react";
import { CheckCircle, FastForward, Image as ImageIcon, X, WarningCircle } from "@phosphor-icons/react";
import {
  approveGate,
  getAssets,
  getAssetImageUrl,
  overrideGate,
  type AssetInfo,
  type QualityGateInfo,
} from "../api/client";
import { btnGhost, btnPrimary, card } from "./ui";

interface AssetApprovalModalProps {
  open: boolean;
  projectId: string;
  /** Numeric DB project id used for the assets fetch. */
  projectDbId: number | null;
  gate: QualityGateInfo | null;
  onClose: () => void;
  onResolved: (gate: QualityGateInfo) => void;
}

const TYPE_LABELS: Record<string, string> = {
  character: "Nhân vật",
  product: "Sản phẩm",
  location: "Phong cảnh",
  style: "Phong cách",
};

export default function AssetApprovalModal({
  open,
  projectId,
  projectDbId,
  gate,
  onClose,
  onResolved,
}: AssetApprovalModalProps) {
  const [assets, setAssets] = useState<AssetInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    if (!open || projectDbId === null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAssets(projectDbId)
      .then((res) => {
        if (!cancelled) setAssets(res.assets);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Không tải được danh sách asset.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, projectDbId]);

  if (!open || !gate) return null;

  async function handleApprove() {
    if (!gate) return;
    setWorking(true);
    setError(null);
    try {
      const updated = await approveGate(projectId, gate.id);
      onResolved(updated);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Duyệt không thành công.");
    } finally {
      setWorking(false);
    }
  }

  async function handleOverride() {
    if (!gate) return;
    if (!confirm("Bỏ qua duyệt asset và tiếp tục pipeline ngay?")) return;
    setWorking(true);
    setError(null);
    try {
      const updated = await overrideGate(projectId, gate.id);
      onResolved(updated);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Override không thành công.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="g2-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/80 px-4 py-6"
    >
      <div className={`${card} w-full max-w-2xl overflow-hidden`}>
        <header className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <h2
            id="g2-modal-title"
            className="flex items-center gap-2 text-base font-semibold text-zinc-100"
          >
            <ImageIcon size={18} weight="duotone" className="text-emerald-400" />
            Duyệt ảnh tham chiếu (G2)
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng"
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-100"
          >
            <X size={18} />
          </button>
        </header>

        <div className="max-h-[60vh] overflow-y-auto px-5 py-4">
          <p className="text-sm text-zinc-400">
            Pipeline đang chờ bạn xác nhận các ảnh tham chiếu. Veo3 sẽ dùng những ảnh
            này làm "neo" để giữ nhân vật / sản phẩm / phong cảnh nhất quán giữa các cảnh.
          </p>

          {error && (
            <div
              role="alert"
              className="mt-3 flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
            >
              <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-rose-400" />
              {error}
            </div>
          )}

          {loading ? (
            <p className="mt-4 text-sm text-zinc-500">Đang tải asset…</p>
          ) : assets.length === 0 ? (
            <p className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              Dự án chưa có ảnh tham chiếu. Bạn có thể bấm
              <strong className="mx-1">Bỏ qua (override)</strong>
              để tiếp tục mà không neo asset, hoặc đóng modal, upload ảnh ở Timeline rồi
              quay lại duyệt sau.
            </p>
          ) : (
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {assets.map((asset) => (
                <div
                  key={asset.id}
                  className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]"
                >
                  <img
                    src={getAssetImageUrl(asset.id)}
                    alt={asset.name}
                    className="aspect-square w-full object-cover"
                    loading="lazy"
                  />
                  <div className="px-2.5 py-2">
                    <p className="truncate text-xs font-medium text-zinc-100">{asset.name}</p>
                    <p className="text-[10px] text-zinc-500">
                      {TYPE_LABELS[asset.type] ?? asset.type}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 bg-white/[0.02] px-5 py-3">
          <p className="text-xs text-zinc-500">
            SLA: G2 sẽ tự hết hạn sau 24h nếu không có hành động.
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleOverride()}
              disabled={working}
              className={btnGhost}
              title="Tiếp tục pipeline mà không neo asset"
            >
              <FastForward size={14} weight="duotone" />
              Bỏ qua (override)
            </button>
            <button
              type="button"
              onClick={() => void handleApprove()}
              disabled={working}
              className={btnPrimary}
            >
              <CheckCircle size={14} weight="duotone" />
              Duyệt và tiếp tục
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
