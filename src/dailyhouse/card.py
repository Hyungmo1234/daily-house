"""오늘 브리핑을 인스타 피드용 JPEG 카드(4:5)로 그린다."""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Settings

log = logging.getLogger(__name__)

W, H = 1080, 1350
NAVY = (27, 42, 65)
TEAL = (14, 159, 142)
ORANGE = (242, 125, 38)
WHITE = (255, 255, 255)
SLATE = (226, 232, 240)
MUTED = (148, 163, 184)
CARD_BG = (20, 33, 52)

FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\malgunbd.ttf"),
    Path(r"C:\Windows\Fonts\malgun.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
]


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    paths = FONT_CANDIDATES if bold else list(reversed(FONT_CANDIDATES))
    for p in paths:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


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


def render_card(day: dict, dest: Path) -> Path:
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 14), fill=TEAL)

    f_brand = _font(36)
    f_date = _font(52)
    f_kicker = _font(26)
    f_num = _font(34)
    f_cat = _font(22)
    f_title = _font(34)
    f_sum = _font(24)
    f_foot = _font(22)

    d.text((64, 48), "Daily House", font=f_brand, fill=TEAL)
    d.text((64, 108), day.get("date_label", ""), font=f_date, fill=WHITE)
    d.text((64, 180), "오늘 부동산에서 꼭 볼 3가지", font=f_kicker, fill=MUTED)

    heads = headlines_of(day)
    y = 240
    box_h = 300
    for i, a in enumerate(heads, 1):
        d.rounded_rectangle((48, y, W - 48, y + box_h), radius=24, fill=CARD_BG)
        d.ellipse((72, y + 28, 124, y + 80), fill=ORANGE if i == 1 else TEAL)
        d.text((90, y + 34), str(i), font=f_num, fill=WHITE)
        cat = a.get("category") or ""
        d.text((148, y + 40), cat, font=f_cat, fill=TEAL)

        title_lines = _wrap(d, a.get("title", ""), f_title, W - 220, 2)
        ty = y + 96
        for line in title_lines:
            d.text((72, ty), line, font=f_title, fill=WHITE)
            ty += 46

        summary = ""
        if a.get("summary"):
            summary = a["summary"][0]
        elif a.get("why"):
            summary = a["why"]
        for line in _wrap(d, summary, f_sum, W - 160, 2):
            d.text((72, ty + 8), line, font=f_sum, fill=SLATE)
            ty += 36
        y += box_h + 20

    d.text((64, H - 72), "전체 기사 · 프로필 링크", font=f_foot, fill=MUTED)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=90, optimize=True)
    log.info("instagram card: %s", dest)
    return dest


def card_path_for(settings: Settings, date_str: str) -> Path:
    return settings.site_dir / "cards" / f"{date_str}.jpg"


def ensure_card(settings: Settings, day: dict) -> Path:
    dest = card_path_for(settings, day["date"])
    return render_card(day, dest)
