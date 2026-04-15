FROM python:3.11-slim

WORKDIR /app

COPY consumer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 임베딩 모델 사전 다운로드 (콜드스타트 방지)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# 공유 모듈 복사
COPY src/storage/chromadb.py ./storage/chromadb.py
COPY src/crawler/base.py ./crawler/base.py
RUN touch storage/__init__.py crawler/__init__.py

COPY consumer/consumer.py .

CMD ["python", "-u", "consumer.py"]
