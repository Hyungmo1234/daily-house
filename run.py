"""Daily House 실행 진입점.

  python run.py                      # 수집 → 요약(LLM) → 저장 → 사이트 빌드
  python run.py --skip-if-exists     # 오늘 치가 있으면 수집 생략 (백업 cron용)
  python run.py --no-llm             # OpenAI 호출 없이 실행
  python run.py --limit 10           # 기사 10건만 처리
  python run.py --build-only         # data/*.json 으로 사이트만 다시 생성
  python run.py --instagram          # 오늘 카드로 인스타 피드 게시 (키 없으면 카드만)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dailyhouse.build import build_site  # noqa: E402
from dailyhouse.config import load_settings  # noqa: E402
from dailyhouse.instagram import publish_today  # noqa: E402
from dailyhouse.pipeline import run  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Daily House 부동산 뉴스 파이프라인")
    p.add_argument("--no-llm", action="store_true", help="OpenAI 요약 없이 실행")
    p.add_argument("--limit", type=int, default=None, help="처리할 최대 기사 수")
    p.add_argument("--build-only", action="store_true", help="수집 없이 사이트만 빌드")
    p.add_argument("--skip-if-exists", action="store_true", help="오늘 데이터가 있으면 수집·요약을 건너뜀")
    p.add_argument("--instagram", action="store_true", help="오늘 브리핑을 인스타에 게시")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    settings = load_settings()
    if args.instagram:
        publish_today(settings, wait_for_public=True)
        return
    if args.build_only:
        build_site(settings)
        return
    run(settings, use_llm=not args.no_llm, limit=args.limit, skip_if_exists=args.skip_if_exists)


if __name__ == "__main__":
    main()
