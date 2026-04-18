"""ChromaDB HTTP 클라이언트. ONNX 양자화 임베딩으로 JD 를 저장하고 URL 기준 중복 제거."""
import logging
import os
from collections.abc import Iterable

import chromadb

from crawler.base import JobDetail

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "snunlp/KR-SBERT-V40K-klueNLI-augSTS"
_MODEL_DIR = os.environ.get("EMBEDDING_MODEL_DIR", "/app/models")
_ONNX_MODEL_PATH = os.path.join(_MODEL_DIR, "kr-sbert-uint8.onnx")
_TOKENIZER_PATH = os.path.join(_MODEL_DIR, "tokenizer")
_MAX_CHUNK_TOKENS = 510  # 512 - [CLS] - [SEP]
_URL_FETCH_CHUNK = 1000


class OnnxEmbeddingFunction:
    """ONNX 양자화 모델 + 문단 청킹 임베딩 함수. ChromaDB embedding_function 프로토콜 준수."""

    def __init__(
        self,
        model_path: str = _ONNX_MODEL_PATH,
        tokenizer_path: str = _TOKENIZER_PATH,
    ):
        import numpy as np
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self._np = np
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        self.session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"],
        )
        self._input_names = {inp.name for inp in self.session.get_inputs()}
        logger.info("ONNX 임베딩 로드 완료: %s", model_path)

    @staticmethod
    def name() -> str:
        return "onnx_kr_sbert"

    def __call__(self, input: list[str]) -> list[list[float]]:
        np = self._np
        results = []

        for text in input:
            chunks = self._chunk_by_paragraphs(text)
            encoded = self.tokenizer(
                chunks, return_tensors="np", padding=True,
                truncation=True, max_length=512,
            )

            ort_inputs = {
                name: encoded[name]
                for name in self._input_names
                if name in encoded
            }
            outputs = self.session.run(None, ort_inputs)
            token_embeddings = outputs[0]

            attention_mask = encoded["attention_mask"]
            mask_expanded = np.expand_dims(attention_mask, axis=-1)
            sum_embeddings = np.sum(token_embeddings * mask_expanded, axis=1)
            sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
            chunk_embeddings = sum_embeddings / sum_mask

            token_counts = np.sum(attention_mask, axis=1)
            weights = token_counts / np.sum(token_counts)
            weighted_embedding = np.sum(
                chunk_embeddings * weights[:, np.newaxis], axis=0,
            )

            norm = max(float(np.linalg.norm(weighted_embedding)), 1e-9)
            results.append((weighted_embedding / norm).tolist())

        return results

    def _chunk_by_paragraphs(self, text: str) -> list[str]:
        """문단 단위로 텍스트를 분할. 각 chunk 가 _MAX_CHUNK_TOKENS 를 넘지 않도록 그룹핑."""
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if not paragraphs:
            return [text or " "]

        chunks: list[str] = []
        current_lines: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = len(self.tokenizer.encode(para, add_special_tokens=False))

            if para_tokens > _MAX_CHUNK_TOKENS:
                if current_lines:
                    chunks.append("\n".join(current_lines))
                    current_lines = []
                    current_tokens = 0
                chunks.append(para)
                continue

            if current_tokens + para_tokens > _MAX_CHUNK_TOKENS and current_lines:
                chunks.append("\n".join(current_lines))
                current_lines = []
                current_tokens = 0

            current_lines.append(para)
            current_tokens += para_tokens

        if current_lines:
            chunks.append("\n".join(current_lines))

        return chunks or [text or " "]


class ChromaDBStorage:

    def __init__(self, host: str, port: int, collection_name: str = "job_descriptions"):
        self.client = chromadb.HttpClient(host=host, port=port)
        embedding_fn = OnnxEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
        )

    def save(self, detail: JobDetail) -> None:
        """raw_text + tech_stack 을 document 로, 나머지를 metadata 로 저장."""
        parts: list[str] = []
        if detail.raw_text:
            parts.append(detail.raw_text)
        if detail.tech_stack:
            parts.append(f"[기술스택]\n{_tech_stack_to_str(detail.tech_stack)}")

        document = "\n\n".join(parts)
        if not document:
            logger.warning("저장할 텍스트 없음: %s", detail.url)
            return

        self.collection.upsert(
            ids=[detail.url],
            documents=[document],
            metadatas=[{
                "source": detail.source,
                "external_id": detail.external_id,
                "company_name": detail.company_name,
                "title": detail.title,
                "url": detail.url,
                "deadline": detail.deadline,
                "crawled_at": detail.crawled_at,
                "tech_stack": _tech_stack_to_str(detail.tech_stack),
            }],
        )
        logger.info("저장 완료: %s - %s", detail.company_name, detail.title)

    def delete_expired(self, now_iso: str) -> int:
        """마감일이 지난 공고 삭제. 상시채용(deadline="")은 제외."""
        results = self.collection.get(
            where={"$and": [{"deadline": {"$lt": now_iso}}, {"deadline": {"$ne": ""}}]}
        )
        expired_ids = results.get("ids") or []
        if not expired_ids:
            return 0
        self.collection.delete(ids=expired_ids)
        logger.info("마감 공고 %d건 삭제", len(expired_ids))
        return len(expired_ids)

    def get_all_urls(self) -> set[str]:
        """저장된 모든 공고 URL 을 청크 단위로 조회."""
        urls: set[str] = set()
        offset = 0

        while True:
            results = self.collection.get(include=["metadatas"], limit=_URL_FETCH_CHUNK, offset=offset)
            metadatas = results.get("metadatas") or []
            if not metadatas:
                break
            for m in metadatas:
                if m and m.get("url"):
                    urls.add(m["url"])
            if len(metadatas) < _URL_FETCH_CHUNK:
                break
            offset += _URL_FETCH_CHUNK

        return urls


def _tech_stack_to_str(tech_stack: Iterable[str]) -> str:
    return ", ".join(tech_stack)
