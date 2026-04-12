"""passroute-crawler Lambda 핸들러.

EventBridge cron → [job_list_collector] → SQS → [job_detail_crawler] → ChromaDB
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

from crawler.base import JobDetail, JobListingRef
from crawler.registry import get_crawler, iter_sources
from storage.chromadb import ChromaDBStorage

logger = logging.getLogger(__name__)

SQS_BATCH_SIZE = 10
KST = timezone(timedelta(hours=9))


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"필수 환경변수 누락: {name}")
    return val


def _make_storage() -> ChromaDBStorage:
    return ChromaDBStorage(
        host=_required_env("CHROMADB_HOST"),
        port=int(_required_env("CHROMADB_PORT")),
    )


# ── Lambda 1: 목록 수집 (cron) ──


def job_list_collector(event, context):
    """마감 공고 삭제 → 전체 목록 수집 → 신규만 JobDetailQueue 전송."""
    sqs = boto3.client("sqs")
    storage = _make_storage()
    queue_url = _required_env("JOB_DETAIL_QUEUE_URL")

    deleted = storage.delete_expired(datetime.now(KST).isoformat())
    existing_urls = storage.get_all_urls()

    total_new = 0
    for source in iter_sources():
        crawler = get_crawler(source)
        logger.info("source=%s 목록 수집 시작", source)
        refs = crawler.collect_listings()
        logger.info("source=%s 수집 완료: %d건", source, len(refs))

        new_count = _dispatch_new_listings(sqs, queue_url, refs, existing_urls)
        total_new += new_count
        logger.info("source=%s 신규 %d건 SQS 전송", source, new_count)

    return {
        "statusCode": 200,
        "body": json.dumps({"new": total_new, "deleted": deleted}),
    }


def _dispatch_new_listings(
    sqs, queue_url: str, refs: list[JobListingRef], existing_urls: set[str],
) -> int:
    """신규 공고만 JobDetailQueue 로 배치 전송."""
    new_count = 0
    batch: list[dict] = []

    for ref in refs:
        if ref.url in existing_urls:
            continue

        batch.append({
            "Id": str(len(batch)),
            "MessageBody": json.dumps({
                "source": ref.source,
                "external_id": ref.external_id,
                "url": ref.url,
                "company_name": ref.company_name,
                "title": ref.title,
            }, ensure_ascii=False),
        })
        new_count += 1

        if len(batch) == SQS_BATCH_SIZE:
            sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
            batch = []

    if batch:
        sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)

    return new_count


# ── Lambda 2: 상세 크롤러 ──


def job_detail_crawler(event, context):
    """SQS 트리거. 공고 1건 상세 크롤링 → ChromaDB 저장."""
    storage = _make_storage()

    for record in event["Records"]:
        message = json.loads(record["body"])
        ref = JobListingRef(
            source=message["source"],
            external_id=message["external_id"],
            url=message["url"],
            title=message.get("title", ""),
            company_name=message.get("company_name", ""),
        )

        crawler = get_crawler(ref.source)
        logger.info("상세 크롤링: source=%s id=%s (%s)", ref.source, ref.external_id, ref.company_name)

        try:
            detail: JobDetail | None = crawler.fetch_detail(ref)
            if detail is None:
                logger.info("텍스트 JD 없음, 스킵: id=%s", ref.external_id)
                continue
            storage.save(detail)
        except Exception:
            logger.exception("상세 크롤링 실패: id=%s", ref.external_id)
            raise

    return {"statusCode": 200}
