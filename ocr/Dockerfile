FROM python:3.11-slim

# PaddleOCR 런타임 의존성 (libgl: OpenCV용, libglib: 이미지 처리용)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 한국어 모델 미리 다운로드 (첫 요청 콜드스타트 제거)
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='korean', show_log=False)"

COPY ocr_server.py .

EXPOSE 8500
CMD ["uvicorn", "ocr_server:app", "--host", "0.0.0.0", "--port", "8500"]
