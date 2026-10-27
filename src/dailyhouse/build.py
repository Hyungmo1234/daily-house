"""data/*.json → site/ 정적 HTML 생성."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .card import ensure_card
from .classify import CATEGORIES
from .config import KST, Settings

log = logging.getLogger(__name__)

CATEGORY_COLORS = {
    "매매·시세": "bg-blue-100 text-blue-800",
    "전월세": "bg-teal-100 text-teal-800",
    "정책·규제": "bg-orange-100 text-orange-800",
    "분양·청약": "bg-emerald-100 text-emerald-800",
    "금리·대출": "bg-red-100 text-red-800",
    "재건축·개발": "bg-purple-100 text-purple-800",
    "기타": "bg-gray-100 text-gray-700",
}


def _load_days(settings: Settings) -> list[dict]:
    days = []
    for p in sorted(settings.data_dir.glob("????-??-??.json"), reverse=True):
        try:
            days.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning("skip %s: %s", p, e)
    return days


def _fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except Exception:
        return ""


def _fmt_dt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%m/%d %H:%M")
    except Exception:
        return iso


def build_site(settings: Settings) -> None:
    days = _load_days(settings)
    if not days:
        log.warning("no data files; nothing to build")
        return

    env = Environment(
        loader=FileSystemLoader(str(settings.template_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["time"] = _fmt_time
    env.filters["dt"] = _fmt_dt
    env.globals.update(
        site_title=settings.site_title,
        categories=CATEGORIES,
        category_colors=CATEGORY_COLORS,
        built_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    )

    site = settings.site_dir
    (site / "days").mkdir(parents=True, exist_ok=True)
    day_tpl = env.get_template("day.html")
    archive_tpl = env.get_template("archive.html")

    recent = [{"date": d["date"], "label": d["date_label"], "count": len(d["articles"])} for d in days[:14]]

    def ctx_for(day: dict, base: str) -> dict:
        by_id = {a["id"]: a for a in day["articles"]}
        headlines = [by_id[i] for i in day.get("headline_ids", []) if i in by_id]
        return {
            "day": day, "headlines": headlines, "base": base, "recent": recent,
            "is_latest": day["date"] == days[0]["date"],
        }

    # 최신일 = index.html
    (site / "index.html").write_text(day_tpl.render(**ctx_for(days[0], "")), encoding="utf-8")
    # 날짜별 페이지
    for d in days:
        (site / "days" / f"{d['date']}.html").write_text(day_tpl.render(**ctx_for(d, "../")), encoding="utf-8")
    # 아카이브
    (site / "archive.html").write_text(archive_tpl.render(days=days, base="", recent=recent), encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")

    # 최신 데이터 JSON도 함께 공개 (추후 앱/메일 연동용)
    shutil.copyfile(settings.data_dir / f"{days[0]['date']}.json", site / "latest.json")
    try:
        ensure_card(settings, days[0])
    except Exception as e:
        log.warning("instagram card failed: %s", e)
    log.info("site built: %s (%d days)", site, len(days))
