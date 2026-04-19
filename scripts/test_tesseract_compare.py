"""Tesseract OCR 전처리 전/후 비교 테스트.

이미지 JD를 크롤링하여 다음 3가지 방식으로 OCR 결과를 비교한다:
1. 기본 Tesseract (전처리 없음)
2. 전처리 + best 설정 적용
3. 전처리 + best 설정 + psm 4 (가변 텍스트 블록)
"""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import base64
import io
import logging
import time

import pytesseract
from PIL import Image, ImageFilter, ImageOps

from crawler.base import ImageJobDetail
from crawler.jobkorea import JobKoreaCrawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def preprocess(pil_img: Image.Image) -> Image.Image:
    """Tesseract 최적화 전처리 파이프라인."""
    img = pil_img.convert("L")
    img = ImageOps.autocontrast(img, cutoff=5)
    img = img.point(lambda x: 255 if x > 180 else 0)
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    return img


def run_tesseract(pil_img: Image.Image, label: str, lang: str, config: str) -> str:
    start = time.time()
    text = pytesseract.image_to_string(pil_img, lang=lang, config=config)
    elapsed = time.time() - start
    text = text.strip()
    print(f"\n{'='*60}")
    print(f"[{label}] lang={lang}, config='{config}'")
    print(f"소요시간: {elapsed:.1f}초 | 결과: {len(text)}자")
    print(f"{'='*60}")
    print(text[:1500] if text else "(인식 결과 없음)")
    if len(text) > 1500:
        print(f"\n... (이하 {len(text) - 1500}자 생략)")
    return text


def main() -> int:
    max_scan = int(sys.argv[1]) if len(sys.argv) >= 2 else 30

    crawler = JobKoreaCrawler()

    print("\n=== 이미지 JD 탐색 중 (목록 1페이지) ===")
    refs = crawler.fetch_listings_page(1)
    print(f"목록 {len(refs)}건 조회 완료\n")

    for i, ref in enumerate(refs[:max_scan]):
        print(f"[{i+1}/{min(max_scan, len(refs))}] {ref.company_name} | {ref.title}")
        try:
            detail = crawler.fetch_detail(ref)
        except Exception as e:
            print(f"  -> 실패: {e}\n")
            continue

        if not isinstance(detail, ImageJobDetail):
            print(f"  -> 텍스트 JD (스킵)\n")
            continue

        print(f"  -> 이미지 JD 발견! ({len(detail.images_b64)}장)")

        for j, img_b64 in enumerate(detail.images_b64):
            raw = base64.b64decode(img_b64)
            pil_img = Image.open(io.BytesIO(raw)).convert("RGB")
            print(f"\n--- 이미지 {j+1}/{len(detail.images_b64)} ({pil_img.size[0]}x{pil_img.size[1]}) ---")

            preprocessed = preprocess(pil_img)

            # 1. 기본 (전처리 없음, fast 모델)
            run_tesseract(pil_img, "기본", "kor", "")

            # 2. 전처리 + psm 6
            run_tesseract(preprocessed, "전처리+psm6", "kor+eng", "--psm 6 --oem 1")

            # 3. 전처리 + psm 4
            run_tesseract(preprocessed, "전처리+psm4", "kor+eng", "--psm 4 --oem 1")

            # 첫 이미지만 비교
            if j >= 0:
                break

        # 첫 이미지 JD만 테스트
        break

    return 0


if __name__ == "__main__":
    sys.exit(main())
