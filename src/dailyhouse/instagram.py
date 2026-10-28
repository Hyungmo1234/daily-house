"""오늘 브리핑을 인스타 피드 한 장으로 올린다.

필요: Instagram 프로페셔널(비즈니스/크리에이터) 계정 + Meta 앱
      INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_USER_ID
이미지는 GitHub Pages에 올라간 JPEG를 Instagram이 가져간다 (공개 HTTPS URL 필수).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import requests

from .card import clean_title, ensure_card, first_line, headlines_of
from .config import KST, Settings

log = logging.getLogger(__name__)

GRAPH = "https://graph.instagram.com/v22.0"


def compose_caption(day: dict, site_url: str) -> str:
    heads = headlines_of(day)
    lines = [
        f"🏠 Daily House | {day.get('date_label', '')}",
        "",
    ]
    overview = (day.get("overview") or "").strip()
    if overview:
        lines += [overview, ""]
    for i, a in enumerate(heads, 1):
        title = clean_title(a.get("title") or "")
        one = first_line(a)
        lines.append(f"{i}. {title}")
        if one:
            lines.append(f"   {one}")
        lines.append("")
    if site_url:
        lines += ["자세한 기사는 프로필 링크에서 볼 수 있습니다.", site_url, ""]
    tags = ["부동산", "부동산뉴스", "아파트", "DailyHouse"]
    for k in day.get("keywords") or []:
        t = str(k).lstrip("#").replace(" ", "")
        if t and t not in tags:
            tags.append(t)
    lines.append(" ".join(f"#{t}" for t in tags[:12]))
    caption = "\n".join(lines).strip()
    return caption[:2200]


def _wait_public(url: str, tries: int = 12, delay: float = 10.0) -> bool:
    for i in range(tries):
        try:
            r = requests.head(url, timeout=15, allow_redirects=True)
            if r.status_code == 200 and int(r.headers.get("Content-Length") or 1) > 1000:
                return True
            r = requests.get(url, timeout=15, stream=True)
            if r.status_code == 200:
                return True
        except requests.RequestException as e:
            log.info("image not public yet (%s): %s", url, e)
        time.sleep(delay * (1 if i < 4 else 1.5))
    return False


def _graph(method: str, path: str, token: str, **params) -> dict:
    url = f"{GRAPH}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"}
    if method.upper() == "GET":
        r = requests.get(url, params=params, headers=headers, timeout=60)
    else:
        r = requests.request(method, url, json=params, headers=headers, timeout=60)
    try:
        data = r.json()
    except ValueError:
        r.raise_for_status()
        raise
    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"instagram api: {err.get('code')} {err.get('message')}")
    r.raise_for_status()
    return data


def already_posted(day: dict) -> bool:
    ig = day.get("instagram") or {}
    return bool(ig.get("media_id"))


def mark_posted(path: Path, day: dict, media_id: str) -> dict:
    day["instagram"] = {
        "media_id": media_id,
        "posted_at": datetime.now(KST).isoformat(timespec="minutes"),
    }
    path.write_text(json.dumps(day, ensure_ascii=False, indent=2), encoding="utf-8")
    return day


def publish(settings: Settings, day: dict, wait_for_public: bool = True) -> str:
    if already_posted(day):
        log.info("instagram already posted: %s", day["instagram"]["media_id"])
        return day["instagram"]["media_id"]
    if not settings.has_instagram:
        raise SystemExit("INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID 가 없습니다.")

    ensure_card(settings, day)
    image_url = settings.public_url(f"cards/{day['date']}.jpg")
    if wait_for_public and not _wait_public(image_url):
        raise RuntimeError(f"공개 이미지 URL을 아직 가져오지 못했습니다: {image_url}")

    caption = compose_caption(day, settings.public_url())
    created = _graph(
        "POST",
        f"{settings.instagram_user_id}/media",
        settings.instagram_access_token,
        image_url=image_url,
        caption=caption,
        alt_text=f"{day.get('date_label', '')} 부동산 뉴스 브리핑",
    )
    container_id = created["id"]
    code = ""
    for _ in range(20):
        st = _graph("GET", container_id, settings.instagram_access_token, fields="status_code")
        code = (st.get("status_code") or "").upper()
        if code in ("FINISHED", "PUBLISHED"):
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"instagram container {code}: {st}")
        time.sleep(4)
    if code not in ("FINISHED", "PUBLISHED"):
        raise RuntimeError(f"instagram container not ready: {code or 'UNKNOWN'}")

    published = _graph(
        "POST",
        f"{settings.instagram_user_id}/media_publish",
        settings.instagram_access_token,
        creation_id=container_id,
    )
    media_id = published["id"]
    log.info("instagram published media_id=%s", media_id)
    return media_id


def publish_today(settings: Settings, wait_for_public: bool = True) -> dict | None:
    now = datetime.now(KST)
    path = settings.data_dir / f"{now.strftime('%Y-%m-%d')}.json"
    if not path.exists():
        raise SystemExit(f"오늘 데이터 파일이 없어 인스타 게시를 할 수 없습니다: {path}")
    day = json.loads(path.read_text(encoding="utf-8"))
    if already_posted(day):
        log.info("이미 게시한 날짜입니다 (%s)", day["instagram"]["media_id"])
        return day
    if not settings.has_instagram:
        raise SystemExit("INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID 가 없습니다.")
    media_id = publish(settings, day, wait_for_public=wait_for_public)
    return mark_posted(path, day, media_id)
