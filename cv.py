"""Đọc CV (PDF / DOCX / TXT) và rút ra hồ sơ: kỹ năng, chức danh, số năm kinh nghiệm."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

# Từ điển kỹ năng: tên chuẩn -> các cách viết khác
SKILLS: dict[str, list[str]] = {
    # ngôn ngữ / công nghệ
    "python": [], "java": [], "javascript": ["js"], "typescript": ["ts"], "c#": ["csharp"],
    "c++": ["cpp"], "go": ["golang"], "rust": [], "php": [], "ruby": [], "kotlin": [],
    "swift": [], "scala": [], "sql": [], "html": [], "css": [], "bash": ["shell"],
    "react": ["reactjs", "react.js"], "vue": ["vuejs", "vue.js"], "angular": [],
    "next.js": ["nextjs"], "node.js": ["nodejs", "node"], "django": [], "flask": [],
    "fastapi": [], "spring": ["spring boot"], ".net": ["dotnet", "asp.net"],
    "laravel": [], "flutter": [], "react native": [], "android": [], "ios": [],
    "docker": [], "kubernetes": ["k8s"], "aws": ["amazon web services"], "azure": [],
    "gcp": ["google cloud"], "terraform": [], "ci/cd": ["cicd", "jenkins", "github actions"],
    "linux": [], "git": [], "postgresql": ["postgres"], "mysql": [], "mongodb": [],
    "redis": [], "elasticsearch": [], "kafka": [], "graphql": [], "rest api": ["restful"],
    "microservices": [], "machine learning": ["ml"], "deep learning": [],
    "nlp": ["natural language processing"], "pytorch": [], "tensorflow": [],
    "pandas": [], "spark": ["pyspark"], "airflow": [], "power bi": ["powerbi"],
    "tableau": [], "excel": [], "data analysis": ["data analytics"], "etl": [],
    "selenium": [], "playwright": [], "testing": ["qa", "test automation"],
    "figma": [], "ui/ux": ["ux", "ui design"], "photoshop": [], "illustrator": [],
    # kinh doanh / khác
    "marketing": [], "seo": [], "content": ["copywriting"], "social media": [],
    "sales": [], "accounting": ["kế toán"], "finance": ["tài chính"],
    "project management": ["pmp", "quản lý dự án"], "scrum": ["agile"],
    "product management": ["product owner"], "business analysis": ["business analyst", "ba"],
    "customer service": ["chăm sóc khách hàng"], "recruitment": ["tuyển dụng"],
    "english": ["tiếng anh", "ielts", "toeic"], "japanese": ["tiếng nhật", "jlpt"],
}

TITLES = [
    "software engineer", "backend developer", "frontend developer", "full stack developer",
    "fullstack developer", "mobile developer", "data analyst", "data scientist",
    "data engineer", "machine learning engineer", "devops engineer", "qa engineer",
    "tester", "business analyst", "product manager", "project manager", "ui/ux designer",
    "designer", "marketing executive", "marketing manager", "content creator",
    "sales executive", "accountant", "hr executive", "recruiter", "customer support",
    "developer", "engineer", "analyst", "manager", "intern",
]


@dataclass
class Profile:
    skills: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    years: int | None = None

    def to_dict(self) -> dict:
        return {"skills": self.skills, "titles": self.titles, "years": self.years}

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(d.get("skills", []), d.get("titles", []), d.get("years"))

    def queries(self, limit: int = 6) -> list[str]:
        """Từ khoá để tìm việc: chức danh trước, rồi các kỹ năng đứng đầu."""
        out = list(self.titles[:3]) + self.skills[:limit]
        seen, res = set(), []
        for q in out:
            if q not in seen:
                seen.add(q)
                res.append(q)
        return res[:limit]


def extract_text(data: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if name.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for t in doc.tables:
            for row in t.rows:
                parts.extend(c.text for c in row.cells)
        return "\n".join(parts)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")
    raise ValueError("Chỉ hỗ trợ file .pdf, .docx, .txt, .md")


def term_regex(term: str) -> re.Pattern:
    # ranh giới từ kiểu "không dính chữ/số" để 'go' không khớp 'good', 'c++' vẫn khớp
    return re.compile(r"(?<![\w+#.])" + re.escape(term.lower()) + r"(?![\w+#])", re.I)


def build_profile(text: str) -> Profile:
    low = text.lower()
    counts: list[tuple[int, str]] = []
    for skill, aliases in SKILLS.items():
        n = sum(len(term_regex(t).findall(low)) for t in [skill, *aliases])
        if n:
            counts.append((n, skill))
    counts.sort(key=lambda x: (-x[0], x[1]))
    skills = [s for _, s in counts]

    titles = [t for t in TITLES if term_regex(t).search(low)]
    # ưu tiên chức danh cụ thể (dài) trước các từ chung chung
    titles.sort(key=lambda t: -len(t))

    years = None
    ys = [int(m) for m in re.findall(r"(\d{1,2})\+?\s*(?:years?|năm)\b", low)]
    ys = [y for y in ys if 0 < y <= 40]
    if ys:
        years = max(ys)
    return Profile(skills, titles, years)
