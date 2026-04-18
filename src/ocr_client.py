"""OCR 서버 HTTP 클라이언트. Lambda 에서 EC2 OCR 서버를 호출한다."""
import logging

import requests

logger = logging.getLogger(__name__)

OCR_TIMEOUT = 30


def call_ocr(images_b64: list[str], server_url: str, api_key: str = "") -> str:
    """이미지 목록을 OCR 서버에 전송하여 텍스트를 추출.

    각 이미지의 OCR 결과를 줄바꿈으로 합산하여 반환한다.
    서버 오류 시 예외를 전파하여 SQS 재시도(DLQ) 로 넘긴다.
    """
    endpoint = f"{server_url.rstrip('/')}/ocr"
    headers = {"X-API-Key": api_key} if api_key else {}
    texts: list[str] = []

    for i, img_b64 in enumerate(images_b64):
        resp = requests.post(
            endpoint,
            json={"image_b64": img_b64},
            headers=headers,
            timeout=OCR_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.json().get("text", "")
        if text:
            texts.append(text)
        logger.info("OCR 이미지 %d/%d 완료: %d자", i + 1, len(images_b64), len(text))

    return "\n".join(texts)
