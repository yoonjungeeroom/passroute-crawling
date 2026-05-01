"""네이버 뉴스 수집 로컬 스모크 테스트.

사용법:
    .venv/bin/python scripts/news_smoke.py                    # 카카오 1개 기업
    .venv/bin/python scripts/news_smoke.py 네이버 삼성전자    # 지정 기업
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from collector.naver_news import NaverNewsCollector, news_item_to_detail_dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    companies = tuple(sys.argv[1:]) if len(sys.argv) > 1 else ("카카오",)

    import os
    client_id = os.environ.get("NAVER_CLIENT_ID", "")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("환경변수 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 를 설정해주세요.")
        print("  export NAVER_CLIENT_ID=xxx")
        print("  export NAVER_CLIENT_SECRET=xxx")
        sys.exit(1)

    collector = NaverNewsCollector(
        client_id=client_id,
        client_secret=client_secret,
        companies=companies,
        api_delay=0.2,
    )

    items = collector.collect_all()

    print(f"\n{'='*60}")
    print(f"수집 결과: {len(items)}건 (기업: {', '.join(companies)})")
    print(f"{'='*60}\n")

    for i, item in enumerate(items[:10], 1):
        d = news_item_to_detail_dict(item)
        print(f"[{i}] {item.title}")
        print(f"    기업: {item.company_name}")
        print(f"    URL: {item.url}")
        print(f"    발행: {item.pub_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"    ID: {d['external_id']}")
        print(f"    설명: {item.description[:80]}...")
        print()

    if len(items) > 10:
        print(f"... 외 {len(items) - 10}건 생략")


if __name__ == "__main__":
    main()
