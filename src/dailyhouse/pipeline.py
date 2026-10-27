"""수집 → 중복 제거 → 관련성 필터 → 요약 → 저장 → 사이트 빌드."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from .build import build_site
from .classify import filter_relevant
from .collect import collect
from .config import KST, Settings
from .dedupe import dedupe, merge_groups
from .summarize import Summarizer, summarize_without_llm

log = logging.getLogger(__name__)

WEEKDAYS = "월화수목금토일"
CLUSTER_MAX = 120  # 한 번의 LLM 호출로 그룹화할 최대 제목 수


def run(settings: Settings, use_llm: bool = True, limit: int | None = None, build: bool = True) -> dict:
    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")

    if not settings.has_naver:
        raise SystemExit("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 .env 에 없습니다.")

    raw = collect(settings, now)
    log.info("collected %d raw articles", len(raw))
    if not raw:
        raise SystemExit("수집된 기사가 없습니다. 키워드/API 키를 확인하세요. 기존 data 파일은 덮어쓰지 않습니다.")
    arts = dedupe(raw)
    log.info("after dedupe: %d", len(arts))
    arts = filter_relevant(arts)
    log.info("after relevance filter: %d", len(arts))

    summarizer = Summarizer(settings) if (use_llm and settings.has_openai) else None
    if use_llm and summarizer is None:
        log.warning("OPENAI_API_KEY 가 없어 LLM 없이 진행합니다.")

    # 2차 중복 제거: LLM이 '같은 사건' 그룹을 묶어주면 병합 (제목이 달라도 같은 발표/대책이면 하나로)
    if summarizer:
        candidates = sorted(arts, key=lambda a: (a.relevance, a.published_at), reverse=True)[:CLUSTER_MAX]
        groups = summarizer.cluster(candidates)
        if groups:
            arts = merge_groups(arts, groups)
            log.info("after story clustering: %d", len(arts))

    # 랭킹: 관련성 + 여러 매체가 다룬 기사 + 주요 매체 우선, 그 다음 최신순 → 상한 적용
    arts.sort(key=lambda a: (a.relevance + 2 * min(a.duplicates, 3) + (3 if a.source_known else 0), a.published_at),
              reverse=True)
    arts = arts[: (limit or settings.max_articles)]

    if summarizer:
        arts = summarizer.summarize(arts)
        brief = summarizer.brief(arts)
        usage = summarizer.usage
    else:
        arts, brief, usage = summarize_without_llm(arts)

    # 최종 정렬: 헤드라인 먼저, 그 다음 중요도 → 최신순
    head = set(brief.headline_ids)
    arts.sort(key=lambda a: (a.id in head, a.importance, a.published_at), reverse=True)

    categories: dict[str, int] = {}
    for a in arts:
        categories[a.category] = categories.get(a.category, 0) + 1

    data = {
        "date": date_str,
        "date_label": f"{now.year}년 {now.month}월 {now.day}일 ({WEEKDAYS[now.weekday()]})",
        "generated_at": now.isoformat(timespec="minutes"),
        "keywords_searched": settings.keywords,
        "overview": brief.overview,
        "keywords": brief.keywords,
        "headline_ids": brief.headline_ids,
        "categories": categories,
        "raw_count": len(raw),
        "articles": [a.to_dict() for a in arts],
        "usage": usage.to_dict(),
    }

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    out = settings.data_dir / f"{date_str}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("saved %s (%d articles)", out, len(arts))
    u = usage.to_dict()
    log.info("LLM usage: %s calls, in=%s (cached %s) out=%s (reasoning %s) ≈ $%s / %s원",
             u["calls"], u["input_tokens"], u["cached_tokens"], u["output_tokens"], u["reasoning_tokens"],
             u["cost_usd"], u["cost_krw"])

    if build:
        build_site(settings)
    return data
