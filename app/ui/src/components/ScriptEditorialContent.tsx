const criterionLabels: Record<string, string> = {
  hook: "Hook & lời hứa", causality: "Quan hệ nhân quả", continuity: "Nhất quán", payoff: "Kết thúc & manh mối",
  speakability: "Lời đọc", visual_feasibility: "Khả năng dựng hình", originality: "Tính nguyên bản",
};
type Finding = { criterion: string; verdict: string; scene_numbers: number[]; evidence: string; suggested_fix: string };

export default function ScriptEditorialContent({ stage, content }: { stage: string; content: Record<string, unknown> }) {
  if (stage === "review") return <div className="my-5 space-y-4">
    <p className="whitespace-pre-wrap text-zinc-200">{String(content.summary ?? "")}</p>
    <p className="text-sm text-amber-200">Đề xuất AI: {content.recommendation === "approve" ? "Có thể đưa vào bước người dùng duyệt" : "Cần sửa"}. Đây chưa phải quyết định duyệt.</p>
    {(content.findings as Finding[] | undefined)?.map((item) => <section key={item.criterion} className="rounded-xl border border-white/10 p-4">
      <h3 className="font-medium">{criterionLabels[item.criterion] ?? item.criterion} · {({ pass: "Đạt theo AI", revise: "Cần sửa", uncertain: "Chưa xác minh" } as Record<string, string>)[item.verdict]}</h3>
      <p className="mt-1 text-xs text-zinc-400">{item.scene_numbers.length ? `Cảnh ${item.scene_numbers.join(", ")}` : "Toàn kịch bản"}</p>
      <p className="mt-2 whitespace-pre-wrap text-sm text-zinc-300">{item.evidence}</p>
      {item.suggested_fix && <p className="mt-2 whitespace-pre-wrap text-sm text-emerald-300">Hướng sửa: {item.suggested_fix}</p>}
    </section>)}
    {Array.isArray(content.issues) && content.issues.length > 0 && <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-300">{content.issues.map((item, index) => <li key={index}>{String(item)}</li>)}</ul>}
  </div>;
  if (stage === "outline") return <div className="my-5 space-y-4">
    {[["logline", "Cốt truyện"], ["opening_hook", "Mở đầu"], ["ending_payoff", "Kết thúc / trả lời câu hỏi"]].map(([key, label]) => <section key={key}>
      <h3 className="font-medium text-emerald-400">{label}</h3><p className="mt-2 whitespace-pre-wrap text-zinc-300">{String(content[key] || "Chưa bổ sung")}</p>
    </section>)}
    <h3 className="font-medium">Nhịp truyện</h3><ol className="list-decimal space-y-3 pl-5 text-sm text-zinc-300">{(content.beats as string[]).map((beat, index) => <li key={index}>{beat}</li>)}</ol>
    <h3 className="font-medium">Manh mối → payoff</h3><ul className="list-disc space-y-2 pl-5 text-sm text-zinc-300">{(content.clue_ledger as string[] | undefined)?.map((clue, index) => <li key={index}>{clue}</li>)}</ul>
    <p className="whitespace-pre-wrap text-sm text-zinc-400">{String(content.continuity_notes ?? "")}</p>
  </div>;
  return <pre className="my-5 max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-black/20 p-4 text-sm text-zinc-300">{JSON.stringify(content, null, 2)}</pre>;
}
