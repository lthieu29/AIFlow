"""Transparent production heuristics, not a prediction of audience retention."""

import re

from server.text.schemas import Brief, Script

QUALITY_VERSION = "script-preflight-2"


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text)


def inspect_script(script: Script, brief: Brief) -> dict:
    issues = []
    scenes = []
    seen_narration = {}
    seen_visual = {}
    def issue(code, severity, message, scene=None):
        issues.append({"code": code, "severity": severity, "message": message, "scene": scene})
    total = sum(scene.duration for scene in script.scenes)
    if abs(total - brief.target_seconds) > max(8, brief.target_seconds * 0.10):
        issue("target_duration", "error", f"Tổng {total:g}s khác mục tiêu {brief.target_seconds}s quá mức cho phép (10% hoặc 8s).")
    for number, scene in enumerate(script.scenes, 1):
        count = len(words(scene.narration))
        estimate = count * 60 / brief.narration_wpm + (0.35 if count else 0)
        scenes.append({"number": number, "words": count, "duration": scene.duration,
                       "estimated_speech_seconds": round(estimate, 1), "start": round(sum(s.duration for s in script.scenes[:number - 1]), 1)})
        if estimate > scene.duration * 1.35:
            issue("speech_overflow", "error", f"{count} từ cần khoảng {estimate:.1f}s, cảnh chỉ {scene.duration:g}s. Rút lời hoặc chia cảnh.", number)
        elif estimate > scene.duration:
            issue("speech_tight", "warning", f"Lời đọc ước tính {estimate:.1f}s vượt {scene.duration:g}s; cần đọc thử/TTS để chốt.", number)
        if any(len(words(sentence)) > 25 for sentence in re.split(r"[.!?]+", scene.narration)):
            issue("long_sentence", "warning", "Câu trên 25 từ; đọc thành tiếng và cân nhắc tách ý.", number)
        normalized = " ".join(words(scene.narration.lower()))
        if normalized and normalized in seen_narration:
            issue("repeated_narration", "warning", f"Lời dẫn trùng cảnh {seen_narration[normalized]}; kiểm tra có chủ đích hay lặp thừa.", number)
        seen_narration[normalized] = number
        visual = " ".join(scene.visual_prompt.lower().split())
        if visual in seen_visual:
            issue("repeated_visual", "warning", f"Prompt hình giống cảnh {seen_visual[visual]}; kiểm tra nhịp hình ảnh.", number)
        seen_visual[visual] = number
        if len(words(scene.visual_prompt)) < 10:
            issue("visual_detail", "warning", "Prompt ngắn: kiểm tra chủ thể, hành động nhìn thấy được, nơi chốn và góc máy.", number)
        if not scene.purpose:
            issue("scene_purpose", "warning", "Chưa ghi cảnh này thay đổi điều gì trong câu chuyện.", number)
    if not any(scene.narration.strip() for scene in script.scenes):
        issue("no_narration", "warning", "Toàn bộ kịch bản không có lời dẫn; xác nhận chủ đích kể chuyện bằng hình.")
    if script.scenes[0].story_beat != "hook":
        issue("opening_hook", "warning", "Chưa đánh dấu hook ở cảnh đầu; kiểm tra lời hứa của tiêu đề trong 30 giây mở đầu.")
    if script.scenes[-1].story_beat != "payoff":
        issue("ending_payoff", "warning", "Chưa đánh dấu payoff ở cảnh cuối; kiểm tra câu hỏi chính đã được trả lời.")
    return {"version": QUALITY_VERSION, "ready": not any(i["severity"] == "error" for i in issues),
            "target_seconds": brief.target_seconds, "total_seconds": round(total, 1),
            "words": sum(item["words"] for item in scenes), "narration_wpm": brief.narration_wpm,
            "scenes": scenes, "issues": issues,
            "disclaimer": "Ước tính biên tập, chưa đo giọng TTS; không chấm được độ hay, tính nguyên bản hoặc retention."}
