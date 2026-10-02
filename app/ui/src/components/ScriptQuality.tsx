export type QualityReport = {
  ready: boolean; total_seconds: number; target_seconds: number; words: number; narration_wpm: number;
  disclaimer: string; issues: { code: string; severity: string; message: string; scene: number | null }[];
  scenes: { number: number; words: number; duration: number; estimated_speech_seconds: number; start: number }[];
};

export const editorialChecks = [
  ["hook_and_promise", "30 giây đầu tạo tò mò và đáp ứng đúng lời hứa của tiêu đề."],
  ["causal_story_and_payoff", "Diễn biến có nguyên nhân; manh mối được gieo trước và kết thúc trả lời câu hỏi chính."],
  ["continuity", "Tên, ngoại hình, đạo cụ, thời gian và quy tắc thế giới nhất quán."],
  ["read_aloud", "Đã đọc thành tiếng: lời dẫn tự nhiên, rõ nghĩa và có khoảng nghỉ."],
  ["visual_feasibility", "Mỗi cảnh có hành động nhìn thấy được, góc máy rõ và dựng được trong 4–8 giây."],
  ["originality", "Đã rà tính nguyên bản và các chi tiết dễ gây hiểu nhầm; không coi AI là công cụ xác minh bản quyền."],
] as const;

export default function ScriptQuality({ report }: { report: QualityReport }) {
  const errors = report.issues.filter((item) => item.severity === "error").length;
  return <section className="my-5 rounded-xl border border-white/10 p-4" aria-label="Kiểm tra trước sản xuất">
    <h3 className="font-semibold">Kiểm tra trước sản xuất · {errors ? `${errors} lỗi cần sửa` : "Không có lỗi chặn tự động"}</h3>
    <p className="mt-2 text-sm text-zinc-300">{report.total_seconds}s / mục tiêu {report.target_seconds}s · {report.words} từ · ước tính {report.narration_wpm} từ/phút</p>
    <p className="mt-2 text-xs text-zinc-400">{report.disclaimer}</p>
    {report.issues.length > 0 && <details className="mt-3" open={errors > 0}>
      <summary className="cursor-pointer text-sm">Xem {report.issues.length} điểm cần rà</summary>
      <ul className="mt-3 max-h-72 space-y-2 overflow-auto text-sm">{report.issues.map((item, index) => <li key={index} className={item.severity === "error" ? "text-rose-300" : "text-amber-200"}>
        <span className="font-medium">{item.severity === "error" ? "Cần sửa" : "Cần rà"}{item.scene ? ` · Cảnh ${item.scene}` : ""}: </span>{item.message}
        {item.scene && <a className="ml-2 underline" href={`#script-scene-${item.scene}`}>Xem cảnh</a>}
      </li>)}</ul>
    </details>}
  </section>;
}
