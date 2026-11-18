"""Lấy tin tuyển dụng từ các nguồn công khai. Mỗi nguồn lỗi thì bỏ qua, không làm hỏng cả lệnh."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger("jobbot.sources")
UA = {"User-Agent": "Mozilla/5.0 (compatible; personal-job-bot/1.0)"}
TIMEOUT = httpx.Timeout(20.0)


@dataclass
class Job:
    title: str
    company: str
    url: str
    location: str = ""
    description: str = ""
    source: str = ""

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.company}|{self.title}|{self.url}".encode()).hexdigest()[:16]


def _text(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)[:4000]


# ---------- Nguồn tổng hợp (tìm theo từ khoá) ----------
async def remotive(c: httpx.AsyncClient, q: str) -> list[Job]:
    r = await c.get("https://remotive.com/api/remote-jobs", params={"search": q, "limit": 50})
    r.raise_for_status()
    return [Job(j["title"], j["company_name"], j["url"], j.get("candidate_required_location", ""),
                _text(j.get("description", "")), "Remotive") for j in r.json().get("jobs", [])]


async def arbeitnow(c: httpx.AsyncClient, q: str) -> list[Job]:
    r = await c.get("https://www.arbeitnow.com/api/job-board-api")
    r.raise_for_status()
    return [Job(j["title"], j["company_name"], j["url"], j.get("location", ""),
                _text(j.get("description", "")), "Arbeitnow") for j in r.json().get("data", [])]


async def remoteok(c: httpx.AsyncClient, q: str) -> list[Job]:
    r = await c.get("https://remoteok.com/api")
    r.raise_for_status()
    return [Job(j["position"], j.get("company", ""), j.get("url") or j.get("apply_url", ""),
                j.get("location", "Remote"), _text(j.get("description", "")), "RemoteOK")
            for j in r.json() if isinstance(j, dict) and j.get("position")]


async def vietnamworks(c: httpx.AsyncClient, q: str) -> list[Job]:
    """API nội bộ của VietnamWorks (không chính thức, có thể đổi bất kỳ lúc nào)."""
    r = await c.post("https://ms.vietnamworks.com/job-search/v1.0/search",
                     json={"query": q, "page": 0, "hitsPerPage": 50, "filter": [], "order": [],
                           "ranges": [], "retrieveFields": []})
    r.raise_for_status()
    jobs = []
    for j in (r.json().get("data") or {}).get("jobs", []):
        title = j.get("jobTitle") or j.get("title") or ""
        url = j.get("jobUrl") or j.get("url") or ""
        if url and url.startswith("/"):
            url = "https://www.vietnamworks.com" + url
        if title:
            jobs.append(Job(title, j.get("companyName", ""), url,
                            ", ".join(j.get("workingLocations", []) and
                                      [w.get("cityNameVI", "") for w in j["workingLocations"]]) or "",
                            _text(j.get("jobDescription", "")), "VietnamWorks"))
    return jobs


def parse_google_jobs(data: dict) -> list[Job]:
    """Google Jobs gom tin từ LinkedIn, Indeed, TopCV, ITviec... Chọn link ứng tuyển tốt nhất."""
    out = []
    for j in data.get("jobs_results", []):
        via = re.sub(r"^via\s+", "", j.get("via", ""), flags=re.I).strip()
        opts = j.get("apply_options") or []
        url = (opts[0].get("link") if opts else None) or j.get("share_link", "")
        out.append(Job(j.get("title", ""), j.get("company_name", ""), url, j.get("location", ""),
                       (j.get("description") or "")[:4000], via or "Google Jobs"))
    return [j for j in out if j.title]


async def google_jobs(c: httpx.AsyncClient, q: str, location: str = "Vietnam") -> list[Job]:
    key = os.getenv("SERPAPI_KEY", "").strip()
    if not key:
        return []
    r = await c.get("https://serpapi.com/search.json",
                    params={"engine": "google_jobs", "q": q, "location": location,
                            "hl": "vi", "gl": "vn", "api_key": key})
    r.raise_for_status()
    return parse_google_jobs(r.json())


def parse_jsearch(data: dict) -> list[Job]:
    out = []
    for j in data.get("data") or []:
        loc = j.get("job_location") or ", ".join(
            x for x in [j.get("job_city"), j.get("job_state"), j.get("job_country")] if x)
        if j.get("job_is_remote") and "remote" not in loc.lower():
            loc = (loc + " (Remote)").strip()
        url = j.get("job_apply_link") or next(
            (o.get("apply_link") for o in j.get("apply_options") or [] if o.get("apply_link")), "")
        out.append(Job(j.get("job_title", ""), j.get("employer_name", ""), url or j.get("job_google_link", ""),
                       loc, (j.get("job_description") or "")[:4000], j.get("job_publisher") or "JSearch"))
    return [j for j in out if j.title]


async def jsearch(c: httpx.AsyncClient, q: str, location: str = "Vietnam") -> list[Job]:
    """JSearch (RapidAPI): gom Google Jobs, LinkedIn, Indeed, Glassdoor..."""
    key = os.getenv("RAPIDAPI_KEY", "").strip()
    if not key:
        return []
    country = os.getenv("JSEARCH_COUNTRY", "vn")
    query = q if not location or location.lower() == "vietnam" else f"{q} in {location}"
    r = await c.get("https://jsearch.p.rapidapi.com/search",
                    params={"query": query, "page": 1, "num_pages": 1, "country": country},
                    headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
    r.raise_for_status()
    return parse_jsearch(r.json())


AGGREGATORS = {"remotive": remotive, "arbeitnow": arbeitnow, "remoteok": remoteok,
               "vietnamworks": vietnamworks}


async def search_all(queries: list[str], location: str | None = None) -> tuple[list[Job], list[str]]:
    """Chạy mọi nguồn song song. Trả (danh sách job đã khử trùng, nguồn bị lỗi)."""
    errors: list[str] = []
    jobs: dict[str, Job] = {}
    async with httpx.AsyncClient(headers=UA, timeout=TIMEOUT, follow_redirects=True) as c:
        async def run(name, fn, q):
            try:
                return await fn(c, q)
            except Exception as e:  # noqa: BLE001
                log.warning("nguồn %s lỗi: %s", name, e)
                if name not in errors:
                    errors.append(name)
                return []
        tasks = []
        for name, fn in AGGREGATORS.items():
            # arbeitnow/remoteok không lọc theo từ khoá → chỉ gọi 1 lần
            qs = queries[:1] if name in ("arbeitnow", "remoteok") else queries
            tasks += [run(name, fn, q) for q in qs]
        if os.getenv("SERPAPI_KEY", "").strip():
            # mỗi truy vấn tốn 1 lượt SerpApi → chỉ lấy 3 từ khoá đầu
            loc = location or os.getenv("JOB_LOCATION", "Vietnam")
            tasks += [run("google_jobs", lambda cl, q, loc=loc: google_jobs(cl, q, loc), q)
                      for q in queries[:3]]
        if os.getenv("RAPIDAPI_KEY", "").strip():
            # mỗi truy vấn tốn 1 request → chỉ lấy 3 từ khoá đầu
            loc = location or os.getenv("JOB_LOCATION", "Vietnam")
            tasks += [run("jsearch", lambda cl, q, loc=loc: jsearch(cl, q, loc), q)
                      for q in queries[:3]]
        for batch in await asyncio.gather(*tasks):
            for j in batch:
                jobs[j.id] = j
    return list(jobs.values()), errors


# ---------- Trang tuyển dụng của công ty ----------
def _slug(url: str, marker: str) -> str | None:
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[0] if parts else None


async def company_jobs(c: httpx.AsyncClient, name: str, careers_url: str | None) -> tuple[list[Job], str]:
    """Trả (job, cách đọc). Nhận ra Greenhouse / Lever / Ashby / Workable; còn lại đọc HTML chung."""
    if not careers_url:
        return [], "none"
    host = urlparse(careers_url).netloc.lower()
    slug = _slug(careers_url, host)
    try:
        if "greenhouse.io" in host and slug:
            r = await c.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
            r.raise_for_status()
            return [Job(j["title"], name, j["absolute_url"], (j.get("location") or {}).get("name", ""),
                        "", "Greenhouse") for j in r.json().get("jobs", [])], "greenhouse"
        if "lever.co" in host and slug:
            r = await c.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
            r.raise_for_status()
            return [Job(j["text"], name, j["hostedUrl"], (j.get("categories") or {}).get("location", ""),
                        _text(j.get("descriptionPlain", "")), "Lever") for j in r.json()], "lever"
        if "ashbyhq.com" in host and slug:
            r = await c.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            r.raise_for_status()
            return [Job(j["title"], name, j.get("jobUrl", careers_url), j.get("location", ""),
                        _text(j.get("descriptionHtml", "")), "Ashby")
                    for j in r.json().get("jobs", [])], "ashby"
        if "workable.com" in host and slug:
            r = await c.post(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", json={"query": ""})
            r.raise_for_status()
            return [Job(j["title"], name, f"https://apply.workable.com/{slug}/j/{j['shortcode']}/",
                        (j.get("location") or {}).get("city", ""), "", "Workable")
                    for j in r.json().get("results", [])], "workable"
    except Exception as e:  # noqa: BLE001
        log.warning("ATS %s lỗi: %s", host, e)
    # Trang tự dựng: lấy các liên kết trông giống tin tuyển dụng
    r = await c.get(careers_url)
    r.raise_for_status()
    return parse_generic_html(r.text, careers_url, name), "html"


JOB_HINT = re.compile(r"(job|career|position|opening|vacanc|tuyen|tuyển|viec|việc|recruit|apply)", re.I)
NOISE = re.compile(r"^(home|about|contact|login|sign|privacy|terms|blog|news|đăng nhập|trang chủ|"
                   r"liên hệ|giới thiệu|read more|xem thêm|apply now|view all|all jobs)\b", re.I)


def parse_generic_html(html: str, base: str, company: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Job] = {}
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = urljoin(base, a["href"])
        if not (8 <= len(text) <= 120) or NOISE.search(text):
            continue
        if not JOB_HINT.search(href) or href.rstrip("/") == base.rstrip("/"):
            continue
        j = Job(text, company, href, "", "", "Trang công ty")
        out[j.id] = j
    return list(out.values())


async def check_company(name: str, careers_url: str | None) -> tuple[list[Job], list[Job], str, list[str]]:
    """Trả (tin trên trang tuyển dụng, tin của công ty trên các sàn, cách đọc, nguồn lỗi)."""
    errors: list[str] = []
    async with httpx.AsyncClient(headers=UA, timeout=TIMEOUT, follow_redirects=True) as c:
        own, how = [], "none"
        if careers_url:
            try:
                own, how = await company_jobs(c, name, careers_url)
            except Exception as e:  # noqa: BLE001
                log.warning("trang tuyển dụng %s lỗi: %s", careers_url, e)
                errors.append("trang tuyển dụng")
    boards, board_errors = await search_all([name])
    key = re.sub(r"\W+", "", name.lower())
    boards = [j for j in boards if key and key in re.sub(r"\W+", "", j.company.lower())]
    return own, boards, how, errors + board_errors
