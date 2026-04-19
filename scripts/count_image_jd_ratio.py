"""이미지 JD 비율 측정 — iframe만 확인하여 빠르게 판별."""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import random
import time

import requests

from crawler.jobkorea import (
    BASE_HEADERS,
    USER_AGENTS,
    JobKoreaCrawler,
)
from parser.jobkorea import parse_job_iframe, IMAGE_JD_TEXT_THRESHOLD

IFRAME_URL = "https://www.jobkorea.co.kr/Recruit/GI_Read_Comt_Ifrm"


def main() -> int:
    max_pages = int(sys.argv[1]) if len(sys.argv) >= 2 else 2
    max_check = int(sys.argv[2]) if len(sys.argv) >= 3 else 80

    crawler = JobKoreaCrawler()

    # 목록 수집
    all_refs = []
    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(random.uniform(1.0, 2.0))
        refs = crawler.fetch_listings_page(page)
        all_refs.extend(refs)
        print(f"페이지 {page}: {len(refs)}건 (누적 {len(all_refs)}건)")

    print(f"\n총 {len(all_refs)}건 중 {min(max_check, len(all_refs))}건 iframe 확인\n")

    text_jd = 0
    image_jd = 0
    empty_jd = 0
    checked = 0

    for ref in all_refs[:max_check]:
        time.sleep(random.uniform(1.0, 2.0))
        try:
            resp = crawler.session.get(IFRAME_URL, params={"Gno": ref.external_id}, timeout=15)
            resp.raise_for_status()
            result = parse_job_iframe(resp.text)

            if result is not None:
                text_jd += 1
                label = "텍스트"
            else:
                # None = 이미지 JD or 빈 페이지
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                text = soup.get_text(separator="\n", strip=True)
                has_img = bool(soup.find_all("img"))

                if len(text) < IMAGE_JD_TEXT_THRESHOLD and has_img:
                    image_jd += 1
                    label = "이미지"
                else:
                    empty_jd += 1
                    label = "빈페이지"
        except Exception as e:
            label = f"에러({e})"
            empty_jd += 1

        checked += 1
        print(f"  [{checked:3d}] {label:6s} | {ref.company_name} | {ref.title[:35]}")

    print(f"\n{'='*50}")
    print(f"결과 ({checked}건)")
    print(f"{'='*50}")
    print(f"  텍스트 JD: {text_jd}건 ({text_jd/checked*100:.1f}%)")
    print(f"  이미지 JD: {image_jd}건 ({image_jd/checked*100:.1f}%)")
    print(f"  빈 페이지: {empty_jd}건 ({empty_jd/checked*100:.1f}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
