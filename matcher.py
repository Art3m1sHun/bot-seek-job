"""Chấm điểm mức phù hợp giữa hồ sơ CV và một tin tuyển dụng (0-100)."""
from __future__ import annotations

from cv import SKILLS, Profile, term_regex


def _variants(skill: str) -> list[str]:
    return [skill, *SKILLS.get(skill, [])]


def score(profile: Profile, title: str, description: str) -> tuple[int, list[str]]:
    """Trả về (điểm, kỹ năng trùng). Kỹ năng trong tiêu đề tính nặng hơn trong mô tả."""
    title_l, desc_l = title.lower(), description.lower()
    matched, pts = [], 0.0
    for skill in profile.skills[:25]:
        pats = [term_regex(v) for v in _variants(skill)]
        in_title = any(p.search(title_l) for p in pats)
        in_desc = any(p.search(desc_l) for p in pats)
        if in_title:
            pts += 3
        elif in_desc:
            pts += 1
        if in_title or in_desc:
            matched.append(skill)

    title_hit = 0
    for t in profile.titles[:5]:
        if term_regex(t).search(title_l):
            title_hit = 1
            break

    # mốc: ~6 điểm kỹ năng ≈ 60 điểm; chức danh khớp cộng 30
    base = min(pts / 6, 1.0) * 60 + title_hit * 30
    if matched:
        base += min(len(matched), 5) * 2  # thưởng độ phủ
    return min(int(round(base)), 100), matched
