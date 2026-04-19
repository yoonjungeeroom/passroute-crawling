"""잡코리아 IT 직군 일일 신규 공고 수 — 목록 페이지 'N일 전 등록'으로 집계."""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import re
import time
import random
from collections import Counter

import requests
from bs4 import BeautifulSoup

from crawler.jobkorea import (
    GI_LIST_URL,
    BASE_HEADERS,
    USER_AGENTS,
    _DEFAULT_CATEGORY_CODES,
)


def fetch_page_with_dates(session, page: int, order: str = "2") -> list[str]:
    """목록 페이지에서 'N일 전 등록' 텍스트를 추출."""
    data = {
        "isDefault": "false",
        "condition[duty]": ",".join(_DEFAULT_CATEGORY_CODES),
        "condition[menucode]": "duty",
        "page": page,
        "direct": "0",
        "order": order,
        "pagesize": "40",
        "tabindex": "0",
        "onePick": "0",
        "confirm": "0",
        "profile": "0",
    }
    resp = session.post(GI_LIST_URL, data=data, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    labels = []

    for row in soup.select("table tbody tr"):
        link = row.select_one('a[href*="/Recruit/GI_Read/"]')
        if not link:
            continue

        time_tag = row.select_one("span.time")
        if time_tag:
            label = time_tag.get_text(strip=True)
            labels.append(label)
        else:
            labels.append("날짜없음")

    return labels


def main() -> int:
    max_pages = int(sys.argv[1]) if len(sys.argv) >= 2 else 50

    session = requests.Session()
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = random.choice(USER_AGENTS)
    headers["X-Requested-With"] = "XMLHttpRequest"
    session.headers.update(headers)

    counter = Counter()
    total = 0

    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(random.uniform(0.5, 1.5))
        labels = fetch_page_with_dates(session, page, order="2")
        if not labels:
            print(f"페이지 {page}: 결과 없음, 종료")
            break
        for label in labels:
            counter[label] += 1
        total += len(labels)

        if page % 10 == 0:
            print(f"  {page}페이지 완료 (누적 {total}건)")

    print(f"\n총 {total}건 분석 완료 ({max_pages}페이지)")
    print(f"\n{'='*50}")
    print(f"등록일 기준 공고 수")
    print(f"{'='*50}")

    for label, count in counter.most_common(30):
        bar = "█" * (count // 2) if count > 2 else "█"
        print(f"  {label:20s}: {count:4d}건  {bar}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
