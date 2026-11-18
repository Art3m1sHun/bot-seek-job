import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cv import build_profile, extract_text
from matcher import score
from sources import parse_generic_html, Job
from store import Store

CV = """Nguyen Van A - Backend Developer
5 years of experience. Python, Django, PostgreSQL, Docker, AWS, REST API, Git. Good communication.
Tiếng Anh IELTS 6.5. Used Go and C++ in school projects."""

def test_profile():
    p = build_profile(CV)
    assert "python" in p.skills and "django" in p.skills and "docker" in p.skills
    assert "c++" in p.skills and "go" in p.skills
    assert "java" not in p.skills and "javascript" not in p.skills
    assert "backend developer" in p.titles and p.years == 5

def test_txt_extract():
    assert "Python" in extract_text(CV.encode(), "cv.txt")

def test_score_ranks():
    p = build_profile(CV)
    good, _ = score(p, "Senior Python Backend Developer", "Django, PostgreSQL, Docker on AWS")
    bad, _ = score(p, "Accountant", "Excel and bookkeeping")
    assert good >= 70 and bad < 25

def test_go_not_in_good():
    p = build_profile("Golang and good vibes")
    assert p.skills == ["go"]
    s, m = score(p, "Chef", "we have good food")
    assert s == 0

def test_generic_html():
    html = '<a href="/careers/senior-engineer-123">Senior Engineer (Hanoi)</a><a href="/about">About us</a>'
    js = parse_generic_html(html, "https://x.com/careers", "X")
    assert [j.title for j in js] == ["Senior Engineer (Hanoi)"]
    assert js[0].url == "https://x.com/careers/senior-engineer-123"

def test_store():
    with tempfile.TemporaryDirectory() as d:
        s = Store(os.path.join(d, "t.db"))
        s.save_cv(1, "a.pdf", build_profile(CV))
        assert s.get_cv(1)[1].skills[0]
        s.add_company(1, "Acme", None)
        cid = s.companies(1)[0]["id"]
        assert s.mark_seen(cid, ["a", "b"]) == {"a", "b"}
        assert s.mark_seen(cid, ["a", "b", "c"]) == {"c"}
        assert s.remove_company(1, "acme") and not s.companies(1)
        assert s.delete_cv(1)


def test_google_jobs_parse():
    from sources import parse_google_jobs
    data = {"jobs_results": [{"title": "Python Dev", "company_name": "FPT", "location": "Hà Nội",
            "via": "via LinkedIn", "description": "Django",
            "apply_options": [{"title": "LinkedIn", "link": "https://linkedin.com/jobs/1"}]},
            {"title": "", "company_name": "x"}]}
    js = parse_google_jobs(data)
    assert len(js) == 1 and js[0].source == "LinkedIn" and js[0].url.endswith("/jobs/1")


def test_jsearch_parse():
    from sources import parse_jsearch
    data = {"status": "OK", "data": [
        {"job_title": "Data Analyst", "employer_name": "VNG", "job_publisher": "LinkedIn",
         "job_apply_link": "https://linkedin.com/jobs/2", "job_city": "Ho Chi Minh City",
         "job_country": "VN", "job_is_remote": True, "job_description": "SQL, Power BI"},
        {"job_title": "X", "employer_name": "Y", "apply_options": [{"apply_link": "https://a.b/c"}]},
        {"employer_name": "no title"}]}
    js = parse_jsearch(data)
    assert len(js) == 2 and js[0].source == "LinkedIn" and "Remote" in js[0].location
    assert js[1].url == "https://a.b/c" and parse_jsearch({"data": None}) == []


def test_jsearch_request_routing(monkeypatch):
    import asyncio, httpx
    import sources
    for k in ("OPENWEBNINJA_KEY", "RAPIDAPI_KEY", "JSEARCH_URL", "JSEARCH_KEY_HEADER"):
        monkeypatch.delenv(k, raising=False)
    assert sources.jsearch_request() is None
    monkeypatch.setenv("RAPIDAPI_KEY", "r")
    assert sources.jsearch_request()[1]["X-RapidAPI-Key"] == "r"
    monkeypatch.setenv("OPENWEBNINJA_KEY", "n")
    url, h = sources.jsearch_request()
    assert url.startswith("https://api.openwebninja.com/") and h == {"x-api-key": "n"}

    seen = {}
    def handler(req):
        seen["url"], seen["key"] = str(req.url), req.headers.get("x-api-key")
        return httpx.Response(200, json={"data": [{"job_title": "Dev", "employer_name": "A"}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await sources.jsearch(c, "python")
    jobs = asyncio.run(run())
    assert jobs[0].title == "Dev" and seen["key"] == "n" and "country=vn" in seen["url"]
