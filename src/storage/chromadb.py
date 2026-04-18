"""ChromaDB HTTP 클라이언트. 사전 계산된 임베딩으로 JD 를 저장하고 URL 기준 중복 제거."""
import logging
from collections.abc import Iterable

import chromadb

from crawler.base import JobDetail

logger = logging.getLogger(__name__)

_URL_FETCH_CHUNK = 1000


class ChromaDBStorage:

    def __init__(self, host: str, port: int, collection_name: str = "job_descriptions"):
        self.client = chromadb.HttpClient(host=host, port=port)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
        )

    def save(self, detail: JobDetail, *, embedding: list[float] | None = None) -> None:
        """사전 계산된 embedding 과 document/metadata 를 ChromaDB 에 저장."""
        parts: list[str] = []
        if detail.raw_text:
            parts.append(detail.raw_text)
        if detail.tech_stack:
            parts.append(f"[기술스택]\n{_tech_stack_to_str(detail.tech_stack)}")

        document = "\n\n".join(parts)
        if not document:
            logger.warning("저장할 텍스트 없음: %s", detail.url)
            return

        upsert_kwargs: dict = {
            "ids": [detail.url],
            "documents": [document],
            "metadatas": [{
                "source": detail.source,
                "external_id": detail.external_id,
                "company_name": detail.company_name,
                "title": detail.title,
                "url": detail.url,
                "deadline": detail.deadline,
                "crawled_at": detail.crawled_at,
                "tech_stack": _tech_stack_to_str(detail.tech_stack),
            }],
        }
        if embedding is not None:
            upsert_kwargs["embeddings"] = [embedding]

        self.collection.upsert(**upsert_kwargs)
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
