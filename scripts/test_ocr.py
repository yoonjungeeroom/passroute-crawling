"""OCR 서버 테스트 — 잡코리아 이미지 JD를 크롤링하여 OCR 결과를 확인한다.
"""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import base64
import logging

import requests

from crawler.base import ImageJobDetail
from crawler.jobkorea import JobKoreaCrawler
from ocr_client import call_ocr
from parser.jobkorea import remove_noise_sections

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

OCR_SERVER_URL = "http://13.209.215.38:8500"
OCR_API_KEY = "vY5k77A29-0VM0-mMlSMJB7kZlSBZmENFEVWxZ1FQPc"


def main() -> int:
    max_scan = int(sys.argv[1]) if len(sys.argv) >= 2 else 20

    crawler = JobKoreaCrawler()

    print("\n=== 이미지 JD 탐색 중 (목록 1페이지) ===")
    refs = crawler.fetch_listings_page(1)
    print(f"목록 {len(refs)}건 조회 완료\n")

    found = 0
    for i, ref in enumerate(refs[:max_scan]):
        print(f"[{i+1}/{min(max_scan, len(refs))}] {ref.company_name} | {ref.title}")
        try:
            detail = crawler.fetch_detail(ref)
        except Exception as e:
            print(f"  → 실패: {e}\n")
            continue

        if not isinstance(detail, ImageJobDetail):
            print(f"  → 텍스트 JD (스킵)\n")
            continue

        # 이미지 JD 발견
        found += 1
        print(f"  → 이미지 JD 발견! ({len(detail.images_b64)}장)")
        print(f"  → OCR 서버 호출 중...")

        try:
            ocr_text = call_ocr(list(detail.images_b64), OCR_SERVER_URL, OCR_API_KEY)
            cleaned = remove_noise_sections(ocr_text)
        except Exception as e:
            print(f"  → OCR 실패: {e}\n")
            continue

        print(f"\n{'='*60}")
        print(f"기업: {detail.company_name}")
        print(f"제목: {detail.title}")
        print(f"URL: {detail.url}")
        print(f"이미지 수: {len(detail.images_b64)}장")
        print(f"{'='*60}")
        print(f"\n--- OCR 원본 텍스트 ({len(ocr_text)}자) ---")
        print(ocr_text[:2000])
        if len(ocr_text) > 2000:
            print(f"\n... (이하 {len(ocr_text) - 2000}자 생략)")
        print(f"\n--- 노이즈 제거 후 ({len(cleaned)}자) ---")
        print(cleaned[:2000])
        if len(cleaned) > 2000:
            print(f"\n... (이하 {len(cleaned) - 2000}자 생략)")
        print()

        # 1건만 테스트하면 충분
        break

    if found == 0:
        print(f"\n앞 {max_scan}건 중 이미지 JD를 찾지 못했습니다.")
        print("더 많은 공고를 탐색하려면: python scripts/test_ocr.py 40")

    return 0


if __name__ == "__main__":
    sys.exit(main())
