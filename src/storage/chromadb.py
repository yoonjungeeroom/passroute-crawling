"""ChromaDB HTTP 클라이언트. 사전 계산된 임베딩으로 JD 를 저장하고 URL 기준 중복 제거."""
import logging
from collections.abc import Iterable
from datetime import datetime, timezone

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
                "deadline": _deadline_to_ts(detail.deadline),
                "crawled_at": detail.crawled_at,
                "tech_stack": _tech_stack_to_str(detail.tech_stack),
                "career_level": detail.career_level,
            }],
        }
        if embedding is not None:
            upsert_kwargs["embeddings"] = [embedding]

        self.collection.upsert(**upsert_kwargs)
        logger.info("저장 완료: %s - %s", detail.company_name, detail.title)

    def delete_expired(self, now_ts: int) -> int:
        """마감일이 지난 공고 삭제. 상시채용(deadline=0)은 제외."""
        deleted = 0
        where = {"$and": [{"deadline": {"$lt": now_ts}}, {"deadline": {"$gt": 0}}]}

        while True:
            results = self.collection.get(where=where, limit=_URL_FETCH_CHUNK)
            expired_ids = results.get("ids") or []
            if not expired_ids:
                break
            self.collection.delete(ids=expired_ids)
            deleted += len(expired_ids)

        if deleted > 0:
            logger.info("마감 공고 %d건 삭제", deleted)
        return deleted

    def migrate_deadline_to_ts(self) -> int:
        """기존 문자열 deadline 을 Unix timestamp 로 마이그레이션한다."""
        migrated = 0
        offset = 0

        while True:
            results = self.collection.get(include=["metadatas"], limit=_URL_FETCH_CHUNK, offset=offset)
            ids = results.get("ids") or []
            metadatas = results.get("metadatas") or []
            if not ids:
                break

            batch_ids: list[str] = []
            batch_metas: list[dict] = []
            for doc_id, meta in zip(ids, metadatas):
                deadline = meta.get("deadline")
                if isinstance(deadline, str):
                    meta["deadline"] = _deadline_to_ts(deadline)
                    batch_ids.append(doc_id)
                    batch_metas.append(meta)

            if batch_ids:
                self.collection.update(ids=batch_ids, metadatas=batch_metas)
                migrated += len(batch_ids)

            if len(ids) < _URL_FETCH_CHUNK:
                break
            offset += _URL_FETCH_CHUNK

        if migrated > 0:
            logger.info("deadline 마이그레이션 완료: %d건", migrated)
        return migrated

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


def _deadline_to_ts(deadline: str) -> int:
    """ISO8601 마감일 문자열을 Unix timestamp(초)로 변환. 빈 문자열(상시채용)은 0."""
    if not deadline:
        return 0
    try:
        dt = datetime.fromisoformat(deadline)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return 0
