"""잡코리아 IT 직군 일일 신규 공고 수를 측정한다 (v2).

상세 페이지 __next_f에서 등록일/수정일을 추출하여 날짜별 집계.
최신업데이트순 정렬이므로, 며칠 전 공고가 나올 때까지만 순회하면 된다.
"""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import re
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

# 먼저 상세 페이지 1개에서 날짜 관련 필드를 전부 찾아본다
def find_date_fields(session, job_id: str) -> None:
    """상세 페이지에서 날짜 관련 필드를 모두 출력."""
    url = f"{DETAIL_URL}/{job_id}"
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    html = resp.text

    # __next_f 스크립트에서 날짜 관련 키 추출
    print(f"\n=== 상세 페이지 날짜 필드 분석 (ID: {job_id}) ===\n")

    # 날짜 관련 키워드로 검색
    date_keywords = [
        "date", "Date", "time", "Time", "reg", "Reg",
        "modify", "Modify", "update", "Update", "create", "Create",
        "post", "Post", "write", "Write", "start", "Start",
    ]

    for keyword in date_keywords:
        pattern = r'\\"(\w*' + keyword + r'\w*)\\":\\"([^"\\]*?)\\"'
        matches = re.findall(pattern, html)
        for key, val in matches:
            if val and len(val) < 50:
                print(f"  {key}: {val}")

    # ISO 날짜 패턴 (2026-04-19 형태)
    iso_dates = re.findall(r'\\"(\w+)\\":\\"(202[456]-\d{2}-\d{2}[T\s]?\d{0,2}:?\d{0,2}:?\d{0,2}[^"\\]*?)\\"', html)
    if iso_dates:
        print(f"\n  ISO 날짜 패턴:")
        for key, val in iso_dates:
            print(f"    {key}: {val}")

    # 숫자 날짜 패턴
    num_dates = re.findall(r'\\"(\w+)\\":\\"(\d{8})\\"', html)
    if num_dates:
        print(f"\n  8자리 숫자 날짜:")
        for key, val in num_dates:
            print(f"    {key}: {val}")

    # registDate, modifyDate 등 직접 검색
    for field in ["registDate", "modifyDate", "postDate", "writeDate", "startDate",
                  "regDate", "regDt", "modDt", "updDt", "createDate", "createdAt",
                  "updatedAt", "openDate", "publishDate"]:
        pattern = r'\\"' + field + r'\\":\\"?([^",\\]+)\\"?'
        match = re.search(pattern, html)
        if match:
            print(f"\n  ** {field} = {match.group(1)}")


def fetch_listing_ids(session, page: int) -> list[str]:
    """목록 페이지에서 job_id 리스트 반환."""
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
    ids = []
    for link in soup.select('a[href*="/Recruit/GI_Read/"]'):
        match = re.search(r'/Recruit/GI_Read/(\d+)', link["href"])
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    return ids


def main() -> int:
    session = requests.Session()
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = random.choice(USER_AGENTS)
    headers["X-Requested-With"] = "XMLHttpRequest"
    session.headers.update(headers)

    # Step 1: 1페이지 첫 공고의 상세 페이지에서 날짜 필드 구조 파악
    ids = fetch_listing_ids(session, 1)
    if not ids:
        print("목록 조회 실패")
        return 1

    print(f"1페이지 공고 {len(ids)}건 조회")

    # 첫 3개 공고에서 날짜 필드 확인
    import time
    for job_id in ids[:3]:
        find_date_fields(session, job_id)
        time.sleep(random.uniform(1.0, 2.0))

    return 0


if __name__ == "__main__":
    sys.exit(main())
