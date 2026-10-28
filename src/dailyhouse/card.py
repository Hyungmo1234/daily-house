"""오늘 브리핑을 인스타 피드용 JPEG 카드(4:5)로 그린다."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Settings

log = logging.getLogger(__name__)

W, H = 1080, 1350
PAPER = (243, 238, 228)
INK = (26, 23, 20)
MUTED = (108, 101, 92)
RULE = (196, 186, 170)
RED = (154, 32, 42)
FOOT = (140, 132, 122)

PREFIX_RE = re.compile(r"^(\[[^\]]+\]\s*)+")
BREAK_CHARS = set(" ·,、.\"'”’)]」』")


def clean_title(title: str) -> str:
    t = PREFIX_RE.sub("", title or "").strip()
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip(".… ")
    if t.count('"') % 2 == 1:
        pre, _, rest = t.partition('"')
        rest = rest.split("…")[0].rstrip(" ,·")
        t = f'{pre.strip()} "{rest}"' if rest else pre.strip()
    return t


def first_line(a: dict) -> str:
    if a.get("why"):
        return a["why"].split(". ")[0].rstrip(".") + "."
    if a.get("summary"):
        return a["summary"][0]
    return ""


_SANS = [
    Path(r"C:\Windows\Fonts\malgun.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
]
_SANS_B = [
    Path(r"C:\Windows\Fonts\malgunbd.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
]
_SERIF = [
    Path(r"C:\Windows\Fonts\georgia.ttf"),
    Path(r"C:\Windows\Fonts\times.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
]
_SERIF_B = [
    Path(r"C:\Windows\Fonts\georgiab.ttf"),
    Path(r"C:\Windows\Fonts\timesbd.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
]


def _pick(paths: list[Path], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _sans(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return _pick(_SANS_B if bold else _SANS, size)


def _serif(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return _pick(_SERIF_B if bold else _SERIF, size)


def _tracked(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill, tracking: float = 6) -> None:
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + tracking


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int, max_lines: int = 3) -> list[str]:
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return []
    lines: list[str] = []
    rest = text
    while rest and len(lines) < max_lines:
        if draw.textlength(rest, font=font) <= max_w:
            lines.append(rest)
            rest = ""
            break
        lo, hi, cut = 1, len(rest), 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if draw.textlength(rest[:mid], font=font) <= max_w:
                cut, lo = mid, mid + 1
            else:
                hi = mid - 1
        if cut < 4:
            cut = min(len(rest), 8)
        for i in range(cut, max(cut // 2, cut - 14), -1):
            if rest[i - 1] in BREAK_CHARS:
                cut = i
                break
        chunk = rest[:cut].rstrip()
        rest = rest[cut:].lstrip()
        if len(lines) == max_lines - 1 and rest:
            while draw.textlength(chunk + "…", font=font) > max_w and len(chunk) > 1:
                chunk = chunk[:-1]
            chunk = chunk.rstrip() + "…"
            rest = ""
        lines.append(chunk)
    return lines


def headlines_of(day: dict) -> list[dict]:
    by_id = {a["id"]: a for a in day.get("articles", [])}
    out = [by_id[i] for i in day.get("headline_ids", []) if i in by_id]
    if not out:
        out = day.get("articles", [])[:3]
    return out[:3]


def _date_bits(day: dict) -> tuple[str, str, str]:
    raw = day.get("date") or ""
    try:
        from datetime import datetime
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        week = "월화수목금토일"[dt.weekday()]
        return f"{dt.month}월 {dt.day}일", f"{dt.year}", week
    except ValueError:
        label = day.get("date_label") or ""
        return label, "", ""


def render_card(day: dict, dest: Path) -> Path:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 10, H), fill=RED)

    mx = 72
    f_mast = _serif(22, bold=True)
    f_week = _sans(20)
    f_date = _sans(58, bold=True)
    f_kicker = _sans(22)
    f_num = _serif(40, bold=True)
    f_cat = _sans(18)
    f_title = _sans(38, bold=True)
    f_dek = _sans(23)
    f_foot = _serif(16)

    date_kr, year, week = _date_bits(day)
    _tracked(d, (mx, 52), "DAILY HOUSE", f_mast, INK, tracking=7)
    if week:
        wtxt = f"{week}요일"
        d.text((W - mx - d.textlength(wtxt, font=f_week), 56), wtxt, font=f_week, fill=MUTED)
    d.line((mx, 98, W - mx, 98), fill=INK, width=2)
    d.text((mx, 118), date_kr, font=f_date, fill=INK)
    d.text((mx, 192), "부동산 브리핑", font=f_kicker, fill=RED)
    if year:
        d.text((W - mx - d.textlength(year, font=f_kicker), 192), year, font=f_kicker, fill=MUTED)
    d.line((mx, 238, W - mx, 238), fill=INK, width=2)

    heads = headlines_of(day)
    y = 268
    block = 300
    for i, a in enumerate(heads, 1):
        if i > 1:
            d.line((mx, y, W - mx, y), fill=RULE, width=1)
            y += 28
        num = f"{i:02d}"
        d.text((mx, y), num, font=f_num, fill=RED)
        cat = a.get("category") or ""
        d.text((mx + 86, y + 14), cat, font=f_cat, fill=MUTED)

        ty = y + 58
        for line in _wrap(d, clean_title(a.get("title", "")), f_title, W - mx * 2, 2):
            d.text((mx, ty), line, font=f_title, fill=INK)
            ty += 50
        ty += 8
        sums = list(a.get("summary") or [])
        dek = (sums[1] if len(sums) > 1 else (sums[0] if sums else first_line(a)))
        for line in _wrap(d, dek, f_dek, W - mx * 2, 2):
            d.text((mx, ty), line, font=f_dek, fill=MUTED)
            ty += 34
        y = max(ty + 36, y + 270)

    d.line((mx, H - 78, W - mx, H - 78), fill=INK, width=1)
    f_foot_kr = _sans(16)
    d.text((mx, H - 56), "오늘의 기사 전체", font=f_foot_kr, fill=FOOT)
    url = "hyungmo1234.github.io/daily-house"
    d.text((W - mx - d.textlength(url, font=f_foot), H - 54), url, font=f_foot, fill=FOOT)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=92, optimize=True)
    log.info("instagram card: %s", dest)
    return dest


def card_path_for(settings: Settings, date_str: str) -> Path:
    return settings.site_dir / "cards" / f"{date_str}.jpg"


def ensure_card(settings: Settings, day: dict) -> Path:
    dest = card_path_for(settings, day["date"])
    return render_card(day, dest)
