"""잡코리아 IT 직군 일일 신규 공고 수를 측정한다 (v3).

firstPostedAt 필드로 날짜별 신규 공고 수를 정확히 집계.
"""
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
    DETAIL_URL,
    BASE_HEADERS,
    USER_AGENTS,
    _DEFAULT_CATEGORY_CODES,
)


def fetch_listing_ids(session, page: int) -> list[tuple[str, str, str]]:
    """목록 페이지에서 (job_id, company, title) 리스트."""
    data = {
        "isDefault": "false",
        "condition[duty]": ",".join(_DEFAULT_CATEGORY_CODES),
        "condition[menucode]": "duty",
        "page": page,
        "direct": "0",
        "order": "3",
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
    seen = set()
    for row in soup.select("table tbody tr"):
        link = row.select_one('a[href*="/Recruit/GI_Read/"]')
        if not link:
            continue
        match = re.search(r'/Recruit/GI_Read/(\d+)', link["href"])
        if not match or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        company = row.select_one('a[href*="/Recruit/Co_Read/"]')
        results.append((
            match.group(1),
            company.get_text(strip=True) if company else "",
            link.get_text(strip=True)[:40],
        ))
    return results


def get_first_posted_at(session, job_id: str) -> str:
    """상세 페이지에서 firstPostedAt 날짜(YYYY-MM-DD)를 추출."""
    url = f"{DETAIL_URL}/{job_id}"
    resp = session.get(url, timeout=15)
    resp.raise_for_status()

    match = re.search(r'\\"firstPostedAt\\":\\"(202\d-\d{2}-\d{2})', resp.text)
    if match:
        return match.group(1)
    return "unknown"


def main() -> int:
    max_pages = int(sys.argv[1]) if len(sys.argv) >= 2 else 5
    # 상세 페이지를 몇 건까지 확인할지 (딜레이 때문에 제한)
    max_details = int(sys.argv[2]) if len(sys.argv) >= 3 else 100

    session = requests.Session()
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = random.choice(USER_AGENTS)
    headers["X-Requested-With"] = "XMLHttpRequest"
    session.headers.update(headers)

    # 여러 페이지의 목록을 먼저 수집
    all_jobs = []
    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(random.uniform(1.0, 2.0))
        items = fetch_listing_ids(session, page)
        if not items:
            break
        all_jobs.extend(items)
        print(f"페이지 {page}: {len(items)}건 (누적 {len(all_jobs)}건)")

    print(f"\n총 {len(all_jobs)}건 목록 수집 완료")
    print(f"상세 페이지에서 firstPostedAt 확인 중 (최대 {max_details}건)...\n")

    date_counter = Counter()
    checked = 0

    for job_id, company, title in all_jobs[:max_details]:
        time.sleep(random.uniform(1.0, 2.0))
        posted_date = get_first_posted_at(session, job_id)
        date_counter[posted_date] += 1
        checked += 1

        if checked % 10 == 0:
            print(f"  {checked}/{min(max_details, len(all_jobs))}건 확인 완료...")

    print(f"\n{'='*50}")
    print(f"날짜별 신규 공고 수 (firstPostedAt 기준)")
    print(f"{'='*50}")
    for date, count in sorted(date_counter.items(), reverse=True):
        bar = "█" * count
        print(f"  {date}: {count:3d}건  {bar}")

    print(f"\n총 {checked}건 분석")
    if checked > 0:
        days = len([d for d in date_counter if d != "unknown"])
        total_known = sum(c for d, c in date_counter.items() if d != "unknown")
        if days > 0:
            print(f"일 평균: {total_known / days:.1f}건 ({days}일간)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
