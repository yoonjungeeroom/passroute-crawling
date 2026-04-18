"""
passroute OCR 서버

이미지 JD를 PaddleOCR로 텍스트 변환하는 얇은 HTTP 래퍼.
ChromaDB EC2에 컨테이너로 띄워서 크롤러 Lambda가 호출한다.
X-API-Key 헤더로 인증한다 (OCR_API_KEY 환경변수).
"""
import base64
import io
import os

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from paddleocr import PaddleOCR
from PIL import Image
from pydantic import BaseModel

app = FastAPI(title="passroute-ocr")

API_KEY = os.environ.get("OCR_API_KEY", "")


def _verify_api_key(request: Request) -> None:
    """API 키 검증. OCR_API_KEY 미설정 시 인증 비활성화."""
    if not API_KEY:
        return
    if request.headers.get("X-API-Key") != API_KEY:
        raise HTTPException(status_code=403, detail="invalid API key")

# 서버 기동 시 1회 로드 (첫 요청 지연 방지)
ocr = PaddleOCR(use_angle_cls=True, lang="korean", show_log=False)


class OCRRequest(BaseModel):
    image_b64: str  # base64 인코딩된 이미지 바이트


class OCRResponse(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/ocr", response_model=OCRResponse, dependencies=[Depends(_verify_api_key)])
def run_ocr(req: OCRRequest):
    try:
        raw = base64.b64decode(req.image_b64)
        img = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid image: {e}")

    result = ocr.ocr(img, cls=True)
    lines = [line[1][0] for page in result if page for line in page]
    return OCRResponse(text="\n".join(lines))
