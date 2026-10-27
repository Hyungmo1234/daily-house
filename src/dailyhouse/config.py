from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")

DEFAULT_KEYWORDS = "부동산,아파트 매매,전세,청약,주택담보대출,분양,재건축"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    openai_api_key: str
    openai_model: str
    naver_client_id: str
    naver_client_secret: str
    keywords: list[str] = field(default_factory=list)
    max_per_keyword: int = 30
    max_articles: int = 30
    lookback_hours: int = 30
    site_title: str = "Daily House"
    site_url: str = ""

    root: Path = ROOT
    data_dir: Path = ROOT / "data"
    site_dir: Path = ROOT / "site"
    template_dir: Path = ROOT / "templates"

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key) and not self.openai_api_key.startswith("sk-여기")

    @property
    def has_naver(self) -> bool:
        return bool(self.naver_client_id and self.naver_client_secret)


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    keywords = [k.strip() for k in _env("NEWS_KEYWORDS", DEFAULT_KEYWORDS).split(",") if k.strip()]
    return Settings(
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_model=_env("OPENAI_MODEL", "gpt-6.1-sol"),
        naver_client_id=_env("NAVER_CLIENT_ID"),
        naver_client_secret=_env("NAVER_CLIENT_SECRET"),
        keywords=keywords,
        max_per_keyword=int(_env("NEWS_MAX_PER_KEYWORD", "30") or 30),
        max_articles=int(_env("NEWS_MAX_TOTAL", "30") or 30),
        lookback_hours=int(_env("NEWS_LOOKBACK_HOURS", "30") or 30),
        site_title=_env("SITE_TITLE", "Daily House"),
        site_url=_env("SITE_URL", ""),
    )
