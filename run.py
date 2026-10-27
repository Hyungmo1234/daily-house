"""Daily House 실행 진입점.

  python run.py                 # 수집 → 요약(LLM) → 저장 → 사이트 빌드
  python run.py --no-llm        # OpenAI 호출 없이 (비용 0) 네이버 요약문으로만 생성
  python run.py --limit 10      # 기사 10건만 처리 (테스트용)
  python run.py --build-only    # data/*.json 으로 사이트만 다시 생성
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dailyhouse.build import build_site  # noqa: E402
from dailyhouse.config import load_settings  # noqa: E402
from dailyhouse.pipeline import run  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Daily House 부동산 뉴스 파이프라인")
    p.add_argument("--no-llm", action="store_true", help="OpenAI 요약 없이 실행")
    p.add_argument("--limit", type=int, default=None, help="처리할 최대 기사 수")
    p.add_argument("--build-only", action="store_true", help="수집 없이 사이트만 빌드")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    settings = load_settings()
    if args.build_only:
        build_site(settings)
        return
    run(settings, use_llm=not args.no_llm, limit=args.limit)


if __name__ == "__main__":
    main()
