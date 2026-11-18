"""
Bot Discord tìm việc theo CV. Chỉ làm việc khi bạn gõ lệnh, không chạy nền.

  /cv file            gửi CV (.pdf / .docx / .txt) để bot đọc kỹ năng
  /hoso               xem hồ sơ bot đã rút ra từ CV
  /timviec            quét các sàn, liệt kê việc hợp CV nhất
  /congty_them        thêm công ty muốn theo dõi (kèm link trang tuyển dụng nếu có)
  /congty_ds          danh sách công ty
  /congty_kiemtra     kiểm tra ngay công ty có đăng tuyển không
  /congty_xoa         bỏ theo dõi
  /xoa_cv             xoá CV đã lưu
"""
from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

from cv import build_profile, extract_text
from matcher import score
from sources import Job, check_company, search_all
from store import Store

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = os.getenv("GUILD_ID", "").strip()
MIN_SCORE = int(os.getenv("MIN_SCORE", "25"))
MAX_CV_BYTES = 8 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jobbot")
store = Store(os.getenv("DB_PATH", "jobs.db"))


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID.isdigit():
            g = discord.Object(int(GUILD_ID))
            self.tree.copy_global_to(guild=g)
            await self.tree.sync(guild=g)
        else:
            await self.tree.sync()


bot = Bot()


def bar(s: int) -> str:
    return "█" * (s // 10) + "░" * (10 - s // 10) + f" {s}%"


def job_line(j: Job, s: int | None = None, matched: list[str] | None = None) -> str:
    head = f"**[{j.title[:90]}]({j.url})**" if j.url else f"**{j.title[:90]}**"
    meta = " · ".join(x for x in [j.company, j.location[:40], j.source] if x)
    out = f"{head}\n{meta}"
    if s is not None:
        out += f"\n`{bar(s)}`"
    if matched:
        out += " " + ", ".join(matched[:6])
    return out


async def send_embeds(inter: discord.Interaction, title: str, lines: list[str], per: int = 5,
                      footer: str = "", ephemeral: bool = True):
    """Chia danh sách thành các embed nhỏ, mỗi tin nhắn tối đa 10 embed."""
    embeds = []
    for i in range(0, len(lines), per):
        e = discord.Embed(title=title if i == 0 else None, description="\n\n".join(lines[i:i + per]),
                          colour=0x5865F2)
        embeds.append(e)
    if footer and embeds:
        embeds[-1].set_footer(text=footer)
    for i in range(0, len(embeds), 10):
        await inter.followup.send(embeds=embeds[i:i + 10], ephemeral=ephemeral)


@bot.tree.command(name="cv", description="Gửi CV/resume (.pdf, .docx, .txt) để bot ghi nhớ")
@app_commands.describe(file="File CV của bạn")
async def cv_cmd(inter: discord.Interaction, file: discord.Attachment):
    await inter.response.defer(ephemeral=True)
    if file.size > MAX_CV_BYTES:
        return await inter.followup.send("File quá lớn (tối đa 8 MB).")
    try:
        text = extract_text(await file.read(), file.filename)
    except ValueError as e:
        return await inter.followup.send(str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("đọc CV lỗi")
        return await inter.followup.send(f"Không đọc được file: {e}")
    if len(text.strip()) < 50:
        return await inter.followup.send(
            "Không trích được chữ từ file (có thể là CV dạng ảnh/scan). Hãy dùng PDF có chọn được chữ hoặc .docx.")
    p = build_profile(text)
    if not p.skills and not p.titles:
        return await inter.followup.send(
            "Đọc được file nhưng không nhận ra kỹ năng nào trong từ điển. Thử `/timviec tu_khoa:...` để tự nhập từ khoá.")
    store.save_cv(inter.user.id, file.filename, p)
    await inter.followup.send(
        f"Đã lưu CV **{file.filename}**.\n**Kỹ năng:** {', '.join(p.skills[:20]) or '—'}\n"
        f"**Chức danh:** {', '.join(p.titles[:5]) or '—'}\n**Kinh nghiệm:** "
        f"{str(p.years) + ' năm' if p.years else 'không rõ'}\n\nGõ `/timviec` để tìm việc.")


@bot.tree.command(name="hoso", description="Xem hồ sơ bot đã rút ra từ CV")
async def hoso(inter: discord.Interaction):
    r = store.get_cv(inter.user.id)
    if not r:
        return await inter.response.send_message("Bạn chưa gửi CV. Dùng `/cv`.", ephemeral=True)
    name, p = r
    await inter.response.send_message(
        f"**{name}**\nKỹ năng: {', '.join(p.skills) or '—'}\nChức danh: {', '.join(p.titles) or '—'}\n"
        f"Kinh nghiệm: {p.years or 'không rõ'}", ephemeral=True)


@bot.tree.command(name="xoa_cv", description="Xoá CV đã lưu")
async def xoa_cv(inter: discord.Interaction):
    ok = store.delete_cv(inter.user.id)
    await inter.response.send_message("Đã xoá CV." if ok else "Bạn chưa có CV nào.", ephemeral=True)


@bot.tree.command(name="timviec", description="Quét các trang tuyển dụng, liệt kê việc hợp với CV")
@app_commands.describe(tu_khoa="Tuỳ chọn: tìm thêm theo từ khoá, vd 'data analyst'",
                       dia_diem="Tuỳ chọn: lọc theo địa điểm, vd 'Ha Noi', 'Remote'",
                       so_luong="Số tin tối đa (mặc định 15)")
async def timviec(inter: discord.Interaction, tu_khoa: str | None = None, dia_diem: str | None = None,
                  so_luong: app_commands.Range[int, 1, 40] = 15):
    await inter.response.defer(ephemeral=True)
    r = store.get_cv(inter.user.id)
    if not r:
        return await inter.followup.send("Bạn chưa gửi CV. Dùng `/cv` trước.")
    _, profile = r
    queries = ([tu_khoa] if tu_khoa else []) + profile.queries()
    jobs, errors = await search_all(queries, dia_diem)
    if dia_diem:
        d = dia_diem.lower()
        jobs = [j for j in jobs if not j.location or d in j.location.lower() or d in j.title.lower()]
    ranked = []
    for j in jobs:
        s, m = score(profile, j.title, j.description)
        if tu_khoa and tu_khoa.lower() in (j.title + " " + j.description).lower():
            s = min(100, s + 15)
        if s >= MIN_SCORE:
            ranked.append((s, j, m))
    ranked.sort(key=lambda x: -x[0])
    note = f"Nguồn không truy cập được: {', '.join(errors)}." if errors else ""
    if not (os.getenv("SERPAPI_KEY", "").strip() or os.getenv("RAPIDAPI_KEY", "").strip() or os.getenv("OPENWEBNINJA_KEY", "").strip()):
        note += " Chưa có OPENWEBNINJA_KEY, RAPIDAPI_KEY hoặc SERPAPI_KEY nên chưa quét LinkedIn/Indeed/TopCV."
    if not ranked:
        return await inter.followup.send(
            f"Quét {len(jobs)} tin nhưng chưa có tin nào đạt {MIN_SCORE}% phù hợp. {note}\n"
            "Thử thêm `tu_khoa`, bỏ `dia_diem`, hoặc hạ `MIN_SCORE` trong `.env`.")
    top = ranked[:so_luong]
    await send_embeds(inter, f"🎯 {len(top)} việc hợp CV nhất (quét {len(jobs)} tin)",
                      [job_line(j, s, m) for s, j, m in top], footer=note)


@bot.tree.command(name="congty_them", description="Thêm công ty muốn theo dõi")
@app_commands.describe(ten="Tên công ty, vd 'FPT Software'",
                       link_tuyen_dung="Tuỳ chọn: link trang tuyển dụng của công ty (giúp kết quả chính xác hơn)")
async def congty_them(inter: discord.Interaction, ten: str, link_tuyen_dung: str | None = None):
    if link_tuyen_dung and not link_tuyen_dung.startswith(("http://", "https://")):
        return await inter.response.send_message("Link phải bắt đầu bằng http:// hoặc https://", ephemeral=True)
    store.add_company(inter.user.id, ten.strip(), link_tuyen_dung)
    await inter.response.send_message(
        f"Đã thêm **{ten}**. Gõ `/congty_kiemtra` để kiểm tra có đăng tuyển không.", ephemeral=True)


@bot.tree.command(name="congty_ds", description="Danh sách công ty đang theo dõi")
async def congty_ds(inter: discord.Interaction):
    rows = store.companies(inter.user.id)
    msg = "\n".join(f"• **{r['name']}**" + (f" — {r['careers_url']}" if r["careers_url"] else "")
                    for r in rows) or "Chưa theo dõi công ty nào. Dùng `/congty_them`."
    await inter.response.send_message(msg[:1900], ephemeral=True)


@bot.tree.command(name="congty_xoa", description="Bỏ theo dõi một công ty")
async def congty_xoa(inter: discord.Interaction, ten: str):
    ok = store.remove_company(inter.user.id, ten.strip())
    await inter.response.send_message("Đã xoá." if ok else "Không tìm thấy công ty này.", ephemeral=True)


@bot.tree.command(name="congty_kiemtra", description="Kiểm tra ngay công ty có đăng tuyển không")
@app_commands.describe(ten="Tuỳ chọn: chỉ kiểm tra công ty này; bỏ trống = tất cả")
async def congty_kiemtra(inter: discord.Interaction, ten: str | None = None):
    await inter.response.defer(ephemeral=True)
    rows = store.companies(inter.user.id)
    if ten:
        rows = [r for r in rows if r["name"].lower() == ten.strip().lower()] or \
               [{"id": None, "name": ten.strip(), "careers_url": None}]
    if not rows:
        return await inter.followup.send("Chưa theo dõi công ty nào. Dùng `/congty_them`.")
    cv = store.get_cv(inter.user.id)
    profile = cv[1] if cv else None
    for r in rows:
        own, boards, how, errors = await check_company(r["name"], r["careers_url"])
        alljobs = {j.id: j for j in own + boards}
        new_ids = store.mark_seen(r["id"], list(alljobs)) if r["id"] else set(alljobs)
        first = bool(r["id"]) and len(new_ids) == len(alljobs)  # lần đầu: chưa có mốc so sánh
        lines = []
        for j in sorted(alljobs.values(), key=lambda j: -(score(profile, j.title, j.description)[0] if profile else 0)):
            tag = "🆕 " if (j.id in new_ids and not first) else ""
            s = score(profile, j.title, j.description)[0] if profile else None
            lines.append(tag + job_line(j, s))
        note = ("Không đọc được: " + ", ".join(errors) + ". ") if errors else ""
        if not r["careers_url"]:
            note += "Chưa có link trang tuyển dụng: chỉ tìm được tin của công ty trên các sàn. "
        if not alljobs:
            await inter.followup.send(f"❌ **{r['name']}**: hiện không thấy tin tuyển dụng nào. {note}")
            continue
        n_new = 0 if first else len(new_ids)
        head = f"✅ {r['name']} đang tuyển {len(alljobs)} vị trí" + \
               (f" — {n_new} tin mới từ lần kiểm tra trước" if n_new else
                " (lần đầu kiểm tra, đã lưu làm mốc để lần sau báo tin mới)" if first else "")
        await send_embeds(inter, head, lines[:20], footer=note.strip())


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Thiếu DISCORD_TOKEN trong file .env")
    bot.run(TOKEN)
