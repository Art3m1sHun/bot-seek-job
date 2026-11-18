"""Dùng Claude để đọc CV và chấm điểm tin tuyển dụng theo ngữ cảnh. Tuỳ chọn: cần ANTHROPIC_API_KEY."""
from __future__ import annotations

import logging
import os
import re

import httpx

from cv import Profile

log = logging.getLogger("jobbot.llm")
API = "https://api.anthropic.com/v1/messages"


def enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def redact(text: str) -> str:
    """Bỏ email, số điện thoại, link khỏi CV trước khi gửi cho AI (không cần cho việc chấm điểm)."""
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text)
    text = re.sub(r"https?://\S+|www\.\S+", "[link]", text)
    text = re.sub(r"(?<!\d)(\+?\d[\d\s().-]{8,}\d)(?!\d)", "[sdt]", text)
    return text


async def call_tool(system: str, user: str, name: str, schema: dict, max_tokens: int = 2000,
                    client: httpx.AsyncClient | None = None) -> dict:
    """Gọi Claude và ép trả kết quả có cấu trúc qua tool use."""
    body = {"model": os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"), "max_tokens": max_tokens,
            "system": system, "messages": [{"role": "user", "content": user}],
            "tools": [{"name": name, "description": "Trả kết quả.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": name}}
    headers = {"x-api-key": os.getenv("ANTHROPIC_API_KEY", ""), "anthropic-version": "2023-06-01"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(90.0))
    try:
        r = await client.post(API, json=body, headers=headers)
        if r.status_code >= 400:
            log.warning("Anthropic HTTP %s: %s", r.status_code, r.text[:300])
        r.raise_for_status()
        for block in r.json().get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == name:
                return block["input"]
        raise ValueError("AI không trả kết quả có cấu trúc")
    finally:
        if own:
            await client.aclose()


PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {"type": "array", "items": {"type": "string"},
                   "description": "1-4 chức danh mục tiêu phù hợp nhất, tiếng Anh, vd 'Backend Developer'"},
        "skills": {"type": "array", "items": {"type": "string"},
                   "description": "Kỹ năng/công nghệ/công cụ thật sự có trong CV, chữ thường, tối đa 30"},
        "seniority": {"type": "string", "enum": ["intern", "fresher", "junior", "mid", "senior", "lead", "manager"]},
        "years": {"type": "integer", "description": "Số năm kinh nghiệm liên quan, 0 nếu chưa có"},
        "search_queries": {"type": "array", "items": {"type": "string"},
                           "description": "3-5 từ khoá tìm việc ngắn (2-4 từ), trộn tiếng Anh và tiếng Việt"},
        "summary": {"type": "string", "description": "Tóm tắt 1-2 câu bằng tiếng Việt về ứng viên"},
    },
    "required": ["titles", "skills", "seniority", "years", "search_queries", "summary"],
}


async def profile_from_cv(text: str) -> Profile:
    d = await call_tool(
        "Bạn là chuyên viên tuyển dụng. Đọc CV và rút hồ sơ ứng viên. Chỉ ghi kỹ năng có thật trong CV, "
        "không bịa. Cấp bậc dựa vào kinh nghiệm thực tế, không dựa vào lời tự nhận.",
        "CV:\n" + redact(text)[:12000], "ghi_ho_so", PROFILE_SCHEMA)
    return Profile(
        skills=[s.lower().strip() for s in d.get("skills", []) if s.strip()][:30],
        titles=[t.lower().strip() for t in d.get("titles", []) if t.strip()][:4],
        years=d.get("years"), summary=d.get("summary", ""), seniority=d.get("seniority", ""),
        extra_queries=[q.strip() for q in d.get("search_queries", []) if q.strip()][:5])


RANK_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"i": {"type": "integer", "description": "số thứ tự tin"},
                       "score": {"type": "integer", "description": "0-100"},
                       "reason": {"type": "string", "description": "Lý do ngắn gọn, tiếng Việt, tối đa 110 ký tự"}},
        "required": ["i", "score", "reason"]}}},
    "required": ["results"],
}


async def rerank(profile: Profile, jobs: list, liked: list[tuple[str, str]],
                 disliked: list[tuple[str, str]]) -> dict[int, tuple[int, str]]:
    """Chấm từng tin 0-100 theo mức phù hợp thực sự. Trả {chỉ số tin: (điểm, lý do)}."""
    lines = []
    for i, j in enumerate(jobs):
        lines.append(f"[{i}] {j.title} | {j.company} | {j.location} | {j.description[:500]}")
    prefs = ""
    if liked:
        prefs += "\nTin ứng viên đã đánh dấu HỢP: " + "; ".join(f"{t} ({c})" for t, c in liked)
    if disliked:
        prefs += "\nTin ứng viên đã đánh dấu KHÔNG HỢP: " + "; ".join(f"{t} ({c})" for t, c in disliked)
    user = (f"ỨNG VIÊN: {profile.summary}\nCấp bậc: {profile.seniority or 'không rõ'}, "
            f"kinh nghiệm: {profile.years if profile.years is not None else 'không rõ'} năm.\n"
            f"Chức danh mục tiêu: {', '.join(profile.titles)}\nKỹ năng: {', '.join(profile.skills[:30])}"
            f"{prefs}\n\nTIN TUYỂN DỤNG:\n" + "\n".join(lines))
    d = await call_tool(
        "Bạn chấm mức phù hợp giữa ứng viên và từng tin tuyển dụng, từ 0 đến 100. Trừ điểm mạnh khi: "
        "khác lĩnh vực, yêu cầu cấp bậc lệch xa (vd ứng viên junior mà tin cần 8 năm), thiếu kỹ năng cốt lõi. "
        "Điểm cao (80+) chỉ cho tin thật sự khớp vai trò và kỹ năng chính. Tham khảo các tin đã đánh dấu "
        "để hiểu sở thích. Chấm đủ mọi tin.", user, "ghi_diem", RANK_SCHEMA,
        max_tokens=min(4000, 120 * len(jobs) + 200))
    out = {}
    for r in d.get("results", []):
        if isinstance(r.get("i"), int) and 0 <= r["i"] < len(jobs):
            out[r["i"]] = (max(0, min(100, int(r.get("score", 0)))), str(r.get("reason", ""))[:140])
    return out
