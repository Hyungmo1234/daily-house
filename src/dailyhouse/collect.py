"""네이버 API HUB 뉴스 검색으로 기사 수집."""
from __future__ import annotations

import hashlib
import html
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

from .config import KST, Settings

log = logging.getLogger(__name__)

NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
TAG_RE = re.compile(r"<[^>]+>")

# 언론사 도메인 → 표시 이름 (없으면 도메인 그대로 표시)
SOURCE_NAMES = {
    "yna.co.kr": "연합뉴스", "newsis.com": "뉴시스", "news1.kr": "뉴스1", "yonhapnewstv.co.kr": "연합뉴스TV",
    "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "sedaily.com": "서울경제", "edaily.co.kr": "이데일리",
    "mt.co.kr": "머니투데이", "fnnews.com": "파이낸셜뉴스", "asiae.co.kr": "아시아경제", "heraldcorp.com": "헤럴드경제",
    "biz.chosun.com": "조선비즈", "chosun.com": "조선일보", "joongang.co.kr": "중앙일보", "donga.com": "동아일보",
    "hani.co.kr": "한겨레", "khan.co.kr": "경향신문", "kmib.co.kr": "국민일보", "segye.com": "세계일보",
    "munhwa.com": "문화일보", "seoul.co.kr": "서울신문", "hankookilbo.com": "한국일보", "kbs.co.kr": "KBS",
    "mbc.co.kr": "MBC", "sbs.co.kr": "SBS", "jtbc.co.kr": "JTBC", "ytn.co.kr": "YTN", "mbn.co.kr": "MBN",
    "news.tvchosun.com": "TV조선", "ichannela.com": "채널A", "newspim.com": "뉴스핌", "etoday.co.kr": "이투데이",
    "dt.co.kr": "디지털타임스", "ajunews.com": "아주경제", "thebell.co.kr": "더벨", "biz.heraldcorp.com": "헤럴드경제",
    "land.naver.com": "네이버부동산", "news.einfomax.co.kr": "연합인포맥스", "nocutnews.co.kr": "노컷뉴스",
    "ohmynews.com": "오마이뉴스", "pressian.com": "프레시안", "sisajournal.com": "시사저널", "etnews.com": "전자신문",
    "zdnet.co.kr": "지디넷코리아", "bizwatch.co.kr": "비즈워치", "dailian.co.kr": "데일리안", "inews24.com": "아이뉴스24",
    "newsway.co.kr": "뉴스웨이", "ekn.kr": "에너지경제", "g-enews.com": "글로벌이코노믹", "news.mtn.co.kr": "머니투데이방송",
    "kookje.co.kr": "국제신문", "busan.com": "부산일보", "kyeongin.com": "경인일보", "joongboo.com": "중부일보",
    "ebn.co.kr": "EBN", "viva100.com": "브릿지경제", "ceoscoredaily.com": "CEO스코어데일리", "goodkyung.com": "굿모닝경제",
    "newdaily.co.kr": "뉴데일리", "straightnews.co.kr": "스트레이트뉴스", "sisaon.co.kr": "시사오늘",
    "kukinews.com": "쿠키뉴스", "m-i.kr": "매일일보", "fntimes.com": "한국금융신문", "thekpm.com": "KPI뉴스",
}


@dataclass
class Article:
    id: str
    title: str
    url: str
    naver_url: str
    source: str
    description: str
    published_at: str  # ISO 8601 (KST)
    keywords: list[str] = field(default_factory=list)
    # 아래는 후처리 단계에서 채움
    relevance: int = 0
    category: str = "기타"
    summary: list[str] = field(default_factory=list)
    importance: int = 3
    tags: list[str] = field(default_factory=list)
    why: str = ""
    duplicates: int = 0
    related: list[dict] = field(default_factory=list)  # 같은 사건을 다룬 다른 매체 기사 [{source,title,url}]

    @property
    def source_known(self) -> bool:
        return self.source in SOURCE_NAMES.values()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source_known"] = self.source_known
        return d


def clean_text(s: str) -> str:
    s = TAG_RE.sub("", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def source_name(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if host in SOURCE_NAMES:
        return SOURCE_NAMES[host]
    # 서브도메인 제거 후 재시도 (news.xxx.co.kr → xxx.co.kr)
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in SOURCE_NAMES:
            return SOURCE_NAMES[cand]
    return host


def _parse_pubdate(s: str) -> datetime | None:
    try:
        return parsedate_to_datetime(s).astimezone(KST)
    except Exception:
        return None


def _make_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


class NaverNewsClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({
            "X-NCP-APIGW-API-KEY-ID": settings.naver_client_id,
            "X-NCP-APIGW-API-KEY": settings.naver_client_secret,
            "User-Agent": "daily-house/0.1",
        })

    def search(self, query: str, display: int = 100, start: int = 1, sort: str = "date") -> list[dict]:
        params = {"query": query, "display": min(max(display, 1), 100), "start": start, "sort": sort}
        for attempt in range(3):
            try:
                r = self.session.get(NAVER_NEWS_URL, params=params, timeout=15)
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json().get("items", [])
            except requests.RequestException as e:
                log.warning("naver search failed (%s, try %d): %s", query, attempt + 1, e)
                time.sleep(1.0 * (attempt + 1))
        return []


def collect(settings: Settings, now: datetime | None = None) -> list[Article]:
    """키워드별로 최신 기사를 수집해 lookback 시간 내 기사만 반환 (중복 제거는 dedupe 단계에서)."""
    now = now or datetime.now(KST)
    cutoff = now - timedelta(hours=settings.lookback_hours)
    client = NaverNewsClient(settings)
    out: dict[str, Article] = {}

    for kw in settings.keywords:
        items = client.search(kw, display=settings.max_per_keyword, sort="date")
        kept = 0
        for it in items:
            pub = _parse_pubdate(it.get("pubDate", ""))
            if pub is None or pub < cutoff:
                continue
            url = (it.get("originallink") or it.get("link") or "").strip()
            if not url:
                continue
            aid = _make_id(url)
            if aid in out:
                if kw not in out[aid].keywords:
                    out[aid].keywords.append(kw)
                continue
            out[aid] = Article(
                id=aid,
                title=clean_text(it.get("title", "")),
                url=url,
                naver_url=(it.get("link") or "").strip(),
                source=source_name(url),
                description=clean_text(it.get("description", "")),
                published_at=pub.isoformat(timespec="minutes"),
                keywords=[kw],
            )
            kept += 1
        log.info("keyword '%s': %d fetched, %d new within %dh", kw, len(items), kept, settings.lookback_hours)
        time.sleep(0.15)  # 호출 간격 (예의상)

    return list(out.values())
