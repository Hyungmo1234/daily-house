"""중복 기사 제거: (1) 제목 유사도 휴리스틱, (2) LLM이 묶어준 '같은 사건' 그룹 병합."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .collect import Article

BRACKET_RE = re.compile(r"[\[\(【<][^\]\)】>]{0,12}[\]\)】>]")  # [속보] (종합) 【단독】 등
NON_WORD_RE = re.compile(r"[^0-9a-zA-Z가-힣]+")
SYNONYMS = [
    ("주택담보대출", "주담대"), ("현대산업개발", "현산"), ("한국은행", "한은"), ("국토교통부", "국토부"),
    ("토지거래허가구역", "토허구역"), ("토지거래허가제", "토허제"), ("서울특별시", "서울시"),
]
STOPWORDS = {"기자", "뉴스", "단독", "속보", "종합", "영상", "포토", "사진", "르포", "오늘", "내일", "올해", "지난",
             "이번", "관련", "대한", "위한", "통해", "따른", "대해", "에서", "으로", "까지", "부터", "그리고"}


def normalize_title(title: str) -> str:
    t = BRACKET_RE.sub(" ", title)
    for long, short in SYNONYMS:
        t = t.replace(long, short)
    t = re.sub(r"(종합|속보|단독|영상|포토|사진|르포|인터뷰|기자수첩|사설|칼럼)\s*[:\-|]?", " ", t)
    return NON_WORD_RE.sub("", t.lower())


def _tokens(title: str) -> set[str]:
    t = BRACKET_RE.sub(" ", title)
    for long, short in SYNONYMS:
        t = t.replace(long, short)
    toks = {w for w in re.split(r"[^0-9a-zA-Z가-힣]+", t.lower()) if len(w) >= 2 and w not in STOPWORDS}
    return toks


def _bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def similar(a: str, b: str, ta: set[str] | None = None, tb: set[str] | None = None) -> bool:
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ba, bb = _bigrams(a), _bigrams(b)
    if len(ba & bb) / max(1, len(ba | bb)) >= 0.6:
        return True
    if ta and tb:
        shared = ta & tb
        if len(shared) >= 4 and len(shared) / max(1, len(ta | tb)) >= 0.4:
            return True
    return SequenceMatcher(None, a, b).ratio() >= 0.82


def _absorb(rep: Article, dup: Article) -> None:
    rep.duplicates += 1
    rep.related.append({"source": dup.source, "title": dup.title, "url": dup.url})
    for kw in dup.keywords:
        if kw not in rep.keywords:
            rep.keywords.append(kw)
    rep.relevance = max(rep.relevance, dup.relevance)


def _better_rep(a: Article, b: Article) -> Article:
    """대표 기사 선택: 주요 매체 > 관련성 > 최신."""
    ka, kb = (a.source_known, a.relevance, a.published_at), (b.source_known, b.relevance, b.published_at)
    return a if ka >= kb else b


def dedupe(articles: list[Article]) -> list[Article]:
    """제목 휴리스틱으로 1차 중복 제거."""
    ordered = sorted(articles, key=lambda a: (a.source_known, a.published_at), reverse=True)
    reps: list[tuple[str, set[str], Article]] = []
    for art in ordered:
        key, toks = normalize_title(art.title), _tokens(art.title)
        for nk, nt, rep in reps:
            if similar(key, nk, toks, nt):
                _absorb(rep, art)
                break
        else:
            reps.append((key, toks, art))
    return [rep for _, _, rep in reps]


def merge_groups(articles: list[Article], groups: list[list[str]]) -> list[Article]:
    """LLM이 '같은 사건'으로 묶은 id 그룹을 병합. 그룹에 없는 기사는 그대로 유지."""
    by_id = {a.id: a for a in articles}
    consumed: set[str] = set()
    for ids in groups:
        members = [by_id[i] for i in ids if i in by_id and i not in consumed]
        if len(members) < 2:
            continue
        rep = members[0]
        for m in members[1:]:
            rep = _better_rep(rep, m)
        for m in members:
            if m is rep:
                continue
            _absorb(rep, m)
            # m 이 이미 흡수한 관련 기사도 승계
            rep.related.extend(m.related)
            rep.duplicates += len(m.related)
            consumed.add(m.id)
    return [a for a in articles if a.id not in consumed]
