"""OpenAI Responses API로 기사 요약 · 분류 · 중요도 평가 · 일일 브리핑 생성."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from openai import OpenAI

from .classify import CATEGORIES
from .collect import Article
from .config import Settings

log = logging.getLogger(__name__)

# USD per 1M tokens: (input, cached input, output)  — 2026-10 기준 공식 가격표
PRICES = {
    "gpt-6-astra": (10.0, 1.0, 50.0),
    "gpt-6.1-sol": (2.0, 0.10, 10.0),
    "gpt-6-sol": (2.0, 0.20, 10.0),
    "gpt-6.1-terra": (1.0, 0.05, 5.0),
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "gpt-5.6-sol": (4.0, 0.40, 20.0),
    "gpt-5.6-terra": (2.0, 0.20, 12.0),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
}
USD_KRW = 1400.0


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    errors: int = 0
    model: str = ""

    def add(self, resp) -> None:
        u = getattr(resp, "usage", None)
        if not u:
            return
        self.calls += 1
        self.input_tokens += u.input_tokens or 0
        self.output_tokens += u.output_tokens or 0
        d_in = getattr(u, "input_tokens_details", None)
        d_out = getattr(u, "output_tokens_details", None)
        self.cached_tokens += getattr(d_in, "cached_tokens", 0) or 0
        self.reasoning_tokens += getattr(d_out, "reasoning_tokens", 0) or 0

    def cost_usd(self) -> float:
        p_in, p_cached, p_out = PRICES.get(self.model, (0.0, 0.0, 0.0))
        uncached = max(0, self.input_tokens - self.cached_tokens)
        return (uncached * p_in + self.cached_tokens * p_cached + self.output_tokens * p_out) / 1_000_000

    def to_dict(self) -> dict:
        usd = self.cost_usd()
        return {
            "model": self.model, "calls": self.calls, "errors": self.errors,
            "input_tokens": self.input_tokens, "cached_tokens": self.cached_tokens,
            "output_tokens": self.output_tokens, "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": round(usd, 4), "cost_krw": round(usd * USD_KRW),
        }


SYSTEM_SUMMARY = f"""당신은 한국 부동산 전문 뉴스 에디터입니다. 입력으로 기사 목록(제목·요약문·출처)을 받으면 각 기사에 대해 아래를 JSON으로 작성합니다.

- relevant: 국내 부동산·주택·건설 시장과 직접 관련 있으면 true. 주식·연예·일반 경제 등 무관하면 false.
- category: {", ".join(CATEGORIES)} 중 하나. 가장 핵심적인 주제 하나만 고릅니다.
- summary: 정확히 3개의 한국어 문장(각 15~45자). 기사에 있는 사실·수치·지역·주체만 사용하고 추측이나 의견을 넣지 않습니다. 각 문장은 명사형이나 '~함/~전망' 등으로 간결하게 끝맺습니다.
- importance: 1~5 정수. 5=전국 시장에 영향을 주는 정책·금리·지표 발표, 4=광역 단위 중요 이슈, 3=일반 시장 소식, 2=지엽적·홍보성, 1=사실상 광고.
- tags: 핵심 키워드 1~3개 (지역명, 정책명, 단지명 등. '#' 없이).

기사에 없는 내용은 절대 만들어내지 마세요. 요약문이 짧아 정보가 부족하면 아는 범위에서만 쓰고 짧게 끝냅니다."""

SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "relevant": {"type": "boolean"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "summary": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                },
                "required": ["id", "relevant", "category", "summary", "importance", "tags"],
            },
        }
    },
    "required": ["items"],
}

SYSTEM_BRIEF = """당신은 부동산 데일리 뉴스레터의 편집장입니다. 오늘 수집된 기사 목록(요약 포함)을 보고 아래를 JSON으로 작성합니다.

- headline_ids: 오늘 독자가 꼭 알아야 할 기사 3개의 id (중요도·파급력·시의성 순). 서로 다른 주제로 고르세요.
- why_it_matters: headline_ids 각각에 대해 "왜 중요한가"를 1~2문장(합계 60~110자)으로. 실수요자·세입자·투자자 중 누구에게 어떤 의미인지 구체적으로. 기사에 없는 사실을 지어내지 마세요.
- overview: 오늘 시장을 한눈에 정리하는 2~3문장(합계 90~160자). 뉴스레터 첫 문단처럼 자연스럽게.
- keywords: 오늘 기사들에서 가장 많이 다뤄진 키워드 5~8개 ('#' 없이, 2~8자)."""

BRIEF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
        "why_it_matters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        },
        "overview": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["headline_ids", "why_it_matters", "overview", "keywords"],
}


SYSTEM_CLUSTER = """당신은 뉴스 데스크 편집자입니다. 기사 제목 목록(id 포함)을 보고 '동일한 사건·발표·보도자료'를 다룬 기사들을 그룹으로 묶습니다.

규칙:
- 같은 회사의 같은 발표, 같은 정부 대책, 같은 통계 발표, 같은 단지의 같은 분양 소식 등 사실상 한 가지 뉴스를 여러 매체가 보도한 경우만 한 그룹입니다.
- 주제가 비슷해도 다른 사건이면 묶지 않습니다 (예: 서로 다른 단지의 청약 소식, 서로 다른 은행의 대출 상품).
- 2개 이상 묶이는 그룹만 출력하고, 단독 기사는 출력하지 않습니다.
- 각 id는 최대 한 그룹에만 속합니다."""

CLUSTER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "topic": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                },
                "required": ["topic", "ids"],
            },
        }
    },
    "required": ["groups"],
}


@dataclass
class Brief:
    headline_ids: list[str] = field(default_factory=list)
    overview: str = ""
    keywords: list[str] = field(default_factory=list)


class Summarizer:
    def __init__(self, settings: Settings, batch_size: int = 8, reasoning: str = "low"):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.batch_size = batch_size
        self.reasoning = reasoning
        self.usage = Usage(model=self.model)

    # ------------------------------------------------------------------ helpers
    def _call(self, system: str, user: str, schema_name: str, schema: dict) -> dict | None:
        try:
            resp = self.client.responses.create(
                model=self.model,
                input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                reasoning={"effort": self.reasoning},
                text={"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
            )
            self.usage.add(resp)
            return json.loads(resp.output_text)
        except Exception as e:  # 네트워크/파싱/모델 오류 모두 폴백
            self.usage.errors += 1
            log.warning("openai call failed (%s): %s", schema_name, e)
            return None

    @staticmethod
    def _article_block(a: Article, with_summary: bool = False) -> str:
        lines = [f"[id={a.id}] {a.title}", f"출처: {a.source} · {a.published_at[11:16]}"]
        if with_summary and a.summary:
            lines.append("요약: " + " / ".join(a.summary))
        else:
            lines.append("요약문: " + (a.description or "(없음)"))
        if a.duplicates:
            lines.append(f"(유사 기사 {a.duplicates}건 추가 보도됨)")
        return "\n".join(lines)

    # ------------------------------------------------------------------ public
    def cluster(self, articles: list[Article]) -> list[list[str]]:
        """같은 사건을 다룬 기사 id 그룹 반환 (실패 시 빈 목록)."""
        if len(articles) < 2:
            return []
        lines = [f"[id={a.id}] ({a.source}) {a.title}" for a in articles]
        data = self._call(SYSTEM_CLUSTER, "기사 제목 목록:\n" + "\n".join(lines), "story_groups", CLUSTER_SCHEMA)
        if not data:
            return []
        groups = [g.get("ids", []) for g in data.get("groups", []) if len(g.get("ids", [])) >= 2]
        for g, meta in zip(groups, data.get("groups", [])):
            log.info("cluster '%s': %d articles", meta.get("topic", ""), len(g))
        return groups

    def summarize(self, articles: list[Article]) -> list[Article]:
        """요약·분류·중요도 채움. relevant=false 기사는 제외해서 반환."""
        kept: list[Article] = []
        for i in range(0, len(articles), self.batch_size):
            batch = articles[i:i + self.batch_size]
            user = "다음 기사들을 처리하세요.\n\n" + "\n\n".join(self._article_block(a) for a in batch)
            data = self._call(SYSTEM_SUMMARY, user, "article_summaries", SUMMARY_SCHEMA)
            by_id = {a.id: a for a in batch}
            if data:
                for item in data.get("items", []):
                    a = by_id.get(item.get("id"))
                    if not a:
                        continue
                    if not item.get("relevant", True):
                        log.info("dropped as irrelevant: %s", a.title)
                        by_id.pop(a.id, None)
                        continue
                    a.category = item.get("category") or a.category
                    a.summary = [s.strip() for s in item.get("summary", []) if s.strip()][:3]
                    a.importance = int(item.get("importance") or 3)
                    a.tags = [t.strip().lstrip("#") for t in item.get("tags", []) if t.strip()][:3]
            # LLM 응답에 누락된 기사는 폴백 요약으로 유지
            for a in by_id.values():
                if not a.summary:
                    a.summary = _fallback_summary(a)
                kept.append(a)
        return kept

    def brief(self, articles: list[Article]) -> Brief:
        if not articles:
            return Brief()
        top = sorted(articles, key=lambda a: (a.importance, a.duplicates, a.published_at), reverse=True)[:20]
        user = "오늘의 기사 목록입니다.\n\n" + "\n\n".join(self._article_block(a, with_summary=True) for a in top)
        data = self._call(SYSTEM_BRIEF, user, "daily_brief", BRIEF_SCHEMA)
        if not data:
            return _fallback_brief(articles)
        ids = {a.id: a for a in articles}
        headline_ids = [i for i in data.get("headline_ids", []) if i in ids][:3]
        for w in data.get("why_it_matters", []):
            if w.get("id") in ids:
                ids[w["id"]].why = w.get("text", "").strip()
        if not headline_ids:
            return _fallback_brief(articles, overview=data.get("overview", ""), keywords=data.get("keywords", []))
        return Brief(
            headline_ids=headline_ids,
            overview=data.get("overview", "").strip(),
            keywords=[k.strip().lstrip("#") for k in data.get("keywords", []) if k.strip()][:8],
        )


# ---------------------------------------------------------------------- fallbacks (LLM 미사용/실패 시)
def _fallback_summary(a: Article) -> list[str]:
    d = a.description or a.title
    parts = [p.strip() for p in d.replace("…", ".").split(". ") if p.strip()]
    return (parts[:3] or [d])[:3]


def _fallback_brief(articles: list[Article], overview: str = "", keywords: list[str] | None = None) -> Brief:
    top = sorted(articles, key=lambda a: (a.importance, a.duplicates, a.relevance), reverse=True)[:3]
    if not keywords:
        counts: dict[str, int] = {}
        for a in articles:
            for t in a.tags or a.keywords:
                counts[t] = counts.get(t, 0) + 1
        keywords = [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:8]]
    return Brief(
        headline_ids=[a.id for a in top],
        overview=overview or f"오늘 수집된 부동산 기사 {len(articles)}건을 카테고리별로 정리했습니다.",
        keywords=keywords,
    )


def summarize_without_llm(articles: list[Article]) -> tuple[list[Article], Brief, Usage]:
    for a in articles:
        a.summary = _fallback_summary(a)
        a.importance = 3 + (1 if a.duplicates >= 2 else 0) + (1 if a.relevance >= 8 else 0)
        a.tags = a.keywords[:3]
    return articles, _fallback_brief(articles), Usage(model="none")
