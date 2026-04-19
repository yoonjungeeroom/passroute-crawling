"""로컬 ONNX OCR 모듈. Lambda 에서 PaddleOCR 한국어 모델을 ONNX 로 직접 추론한다."""
import base64
import io
import logging
import os

logger = logging.getLogger(__name__)

_OCR_MODEL_DIR = os.environ.get("OCR_MODEL_DIR", "/app/ocr_models")
MAX_IMAGE_SIDE = 1500

_ocr_engine = None


def _load_ocr():
    """RapidOCR 엔진을 1회 로딩. Lambda 웜 스타트 시 재사용."""
    global _ocr_engine

    if _ocr_engine is not None:
        return

    from rapidocr_onnxruntime import RapidOCR

    rec_model = os.path.join(_OCR_MODEL_DIR, "korean_rec.onnx")
    rec_dict = os.path.join(_OCR_MODEL_DIR, "korean_dict.txt")

    _ocr_engine = RapidOCR(rec_model_path=rec_model, rec_keys_path=rec_dict)
    logger.info("ONNX OCR 로드 완료: %s", rec_model)


def _preprocess_image(img_b64: str):
    """base64 이미지를 디코딩하고 전처리하여 numpy 배열로 반환."""
    import numpy as np
    from PIL import Image

    raw = base64.b64decode(img_b64)
    pil_img = Image.open(io.BytesIO(raw)).convert("RGB")

    w, h = pil_img.size
    if max(w, h) > MAX_IMAGE_SIDE:
        scale = MAX_IMAGE_SIDE / max(w, h)
        pil_img = pil_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    return np.array(pil_img)


def call_ocr(images_b64: list[str]) -> str:
    """이미지 목록을 로컬 ONNX OCR 로 텍스트 추출.

    각 이미지의 OCR 결과를 줄바꿈으��� 합산하여 반환한다.
    """
    _load_ocr()
    texts: list[str] = []

    for i, img_b64 in enumerate(images_b64):
        img = _preprocess_image(img_b64)
        result, _ = _ocr_engine(img)

        if result:
            lines = [item[1] for item in result]
            text = "\n".join(lines)
            texts.append(text)
        else:
            text = ""

        logger.info("OCR 이미지 %d/%d 완료: %d자", i + 1, len(images_b64), len(text))

    return "\n".join(texts)
