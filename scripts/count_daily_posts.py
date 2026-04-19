"""잡코리아 IT 직군 카테고리의 일일 신규 공고 수를 측정한다.

목록 페이지를 최신업데이트순으로 순회하면서 날짜별 공고 수를 집계한다.
"""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import re
import time
import random
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from crawler.jobkorea import (
    GI_LIST_URL,
    BASE_HEADERS,
    USER_AGENTS,
    _DEFAULT_CATEGORY_CODES,
)

KST = timezone(timedelta(hours=9))


def fetch_listings_with_dates(session, page: int) -> list[dict]:
    """목록 페이지에서 공고 정보 + 날짜를 추출."""
    data = {
        "isDefault": "false",
        "condition[duty]": ",".join(_DEFAULT_CATEGORY_CODES),
        "condition[menucode]": "duty",
        "page": page,
        "direct": "0",
        "order": "3",  # 최신업데이트순
        "pagesize": "40",
        "tabindex": "0",
        "onePick": "0",
        "confirm": "0",
        "profile": "0",
    }
    resp = session.post(GI_LIST_URL, data=data, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    for row in soup.select("table tbody tr"):
        link = row.select_one('a[href*="/Recruit/GI_Read/"]')
        if not link:
            continue

        company_tag = row.select_one('a[href*="/Recruit/Co_Read/"]')
        company = company_tag.get_text(strip=True) if company_tag else ""
        title = link.get_text(strip=True)

        # 날짜 정보 추출 시도 (etc 영역의 모든 span.cell)
        etc_tag = row.select_one("p.etc")
        cells = []
        if etc_tag:
            cells = [s.get_text(strip=True) for s in etc_tag.select("span.cell")]

        # 수정일/등록일 추출 시도
        date_tag = row.select_one("span.date")
        date_text = date_tag.get_text(strip=True) if date_tag else ""

        # 전체 row 텍스트에서 날짜 패턴 찾기
        row_text = row.get_text(" ", strip=True)
        date_patterns = re.findall(r'(\d{2}/\d{2}/\d{2})', row_text)
        date_patterns2 = re.findall(r'(\d{4}-\d{2}-\d{2})', row_text)
        date_patterns3 = re.findall(r'수정일\s*(\S+)', row_text)
        date_patterns4 = re.findall(r'등록일\s*(\S+)', row_text)

        results.append({
            "company": company,
            "title": title[:40],
            "cells": cells,
            "date_tag": date_text,
            "dates_slash": date_patterns,
            "dates_dash": date_patterns2,
            "dates_modified": date_patterns3,
            "dates_registered": date_patterns4,
            "row_text_tail": row_text[-80:],
        })

    return results


def main() -> int:
    max_pages = int(sys.argv[1]) if len(sys.argv) >= 2 else 5

    session = requests.Session()
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = random.choice(USER_AGENTS)
    headers["X-Requested-With"] = "XMLHttpRequest"
    session.headers.update(headers)

    # 먼저 1페이지에서 날짜 구조 파악
    print("=== 1페이지 공고 구조 분석 ===\n")
    items = fetch_listings_with_dates(session, 1)

    for i, item in enumerate(items[:5]):
        print(f"[{i+1}] {item['company']} | {item['title']}")
        print(f"    cells: {item['cells']}")
        print(f"    date_tag: {item['date_tag']}")
        print(f"    dates_slash: {item['dates_slash']}")
        print(f"    dates_dash: {item['dates_dash']}")
        print(f"    dates_modified: {item['dates_modified']}")
        print(f"    dates_registered: {item['dates_registered']}")
        print(f"    tail: {item['row_text_tail']}")
        print()

    # 날짜가 있으면 여러 페이지 순회하며 날짜별 집계
    print(f"\n=== {max_pages}페이지 순회하며 날짜별 집계 ===\n")

    date_counter = Counter()
    total = 0

    for page in range(1, max_pages + 1):
        if page > 1:
            delay = random.uniform(1.0, 2.0)
            time.sleep(delay)

        items = fetch_listings_with_dates(session, page)
        if not items:
            print(f"페이지 {page}: 결과 없음, 종료")
            break

        for item in items:
            total += 1
            # 가장 유력한 날짜 소스 사용
            dates = item["dates_slash"] or item["dates_dash"] or item["dates_modified"] or item["dates_registered"]
            if dates:
                date_counter[dates[-1]] += 1  # 마지막 날짜 (보통 수정일)
            else:
                # cells에서 날짜 패턴 찾기
                for cell in item["cells"]:
                    found = re.search(r'(\d{2}/\d{2}/\d{2}|\d{4}-\d{2}-\d{2})', cell)
                    if found:
                        date_counter[found.group(1)] += 1
                        break
                else:
                    date_counter["날짜없음"] += 1

        print(f"페이지 {page}: {len(items)}건 (누적 {total}건)")

    print(f"\n=== 날짜별 공고 수 (최신순) ===\n")
    for date, count in date_counter.most_common(20):
        print(f"  {date}: {count}건")

    print(f"\n총 {total}건 분석 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
