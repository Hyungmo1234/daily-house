"""규칙 기반 부동산 관련성 점수 + 카테고리 분류 (LLM 실패 시 폴백으로도 사용)."""
from __future__ import annotations

from .collect import Article

CATEGORIES = ["매매·시세", "전월세", "정책·규제", "분양·청약", "금리·대출", "재건축·개발", "기타"]

# 부동산 관련성 판단용 핵심 용어 (제목 가중 2, 본문 가중 1)
CORE_TERMS = [
    "부동산", "아파트", "주택", "전세", "월세", "청약", "분양", "재건축", "재개발", "집값", "매매가",
    "주담대", "주택담보", "국토부", "국토교통부", "토지거래", "임대", "오피스텔", "빌라", "분양가",
    "LH", "HUG", "주택도시", "부동산원", "공시가격", "보유세", "양도세", "취득세", "종부세", "임대차",
    "입주", "미분양", "전세사기", "갭투자", "신도시", "택지", "GTX", "역세권", "도시정비", "리모델링",
    "상가", "건물", "토지", "땅값", "지가", "분양권", "입주권", "다주택", "무주택", "실거주", "전매",
]
# 노이즈 제거: 이 단어가 제목에 있고 핵심 용어가 약하면 제외
NOISE_TERMS = ["주식", "코스피", "코스닥", "비트코인", "가상자산", "연예", "아이돌", "드라마", "영화"]

CATEGORY_RULES: dict[str, list[str]] = {
    "분양·청약": ["청약", "분양", "미분양", "당첨", "경쟁률", "견본주택", "모델하우스", "분양가", "줍줍", "무순위", "특별공급"],
    "금리·대출": ["금리", "주담대", "주택담보", "대출", "DSR", "LTV", "DTI", "기준금리", "한은", "한국은행", "디딤돌", "보금자리론", "스트레스"],
    "정책·규제": ["국토부", "국토교통부", "정부", "대책", "규제", "토지거래허가", "세제", "보유세", "양도세", "취득세", "종부세", "공시가격",
               "국회", "법안", "개정", "정책", "대통령", "서울시", "LH", "공급대책", "임대차", "계약갱신"],
    "재건축·개발": ["재건축", "재개발", "정비사업", "조합", "시공사", "도시정비", "리모델링", "신도시", "택지", "GTX", "개발", "착공", "준공", "선도지구"],
    "전월세": ["전세", "월세", "전셋값", "전세가", "임대료", "세입자", "임차", "역전세", "전세사기", "보증금", "임대"],
    "매매·시세": ["매매", "집값", "시세", "거래량", "상승", "하락", "실거래", "신고가", "호가", "매수", "매도", "급매", "부동산원", "매매가", "주간"],
}


def relevance_score(a: Article) -> int:
    title, desc = a.title, a.description
    score = 0
    for t in CORE_TERMS:
        if t in title:
            score += 2
        elif t in desc:
            score += 1
    if any(n in title for n in NOISE_TERMS) and score < 4:
        score = 0
    return score


def rule_category(a: Article) -> str:
    text_t, text_d = a.title, a.description
    best, best_score = "기타", 0
    for cat, terms in CATEGORY_RULES.items():
        s = 0
        for t in terms:
            if t in text_t:
                s += 2
            if t in text_d:
                s += 1
        if s > best_score:
            best, best_score = cat, s
    return best


def filter_relevant(articles: list[Article], min_score: int = 2) -> list[Article]:
    out = []
    for a in articles:
        a.relevance = relevance_score(a)
        if a.relevance >= min_score:
            if a.category == "기타":
                a.category = rule_category(a)
            out.append(a)
    return out
