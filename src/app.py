"""passroute-crawler Lambda 핸들러.

EventBridge cron → [job_list_collector] → SQS → [job_detail_crawler] → S3 → EC2 consumer → ChromaDB
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

from crawler.base import ImageJobDetail, JobDetail, JobListingRef
from crawler.registry import get_crawler, iter_sources
from embedding import build_document, embed_text
from ocr_client import call_ocr
from parser.jobkorea import remove_noise_sections
from storage.s3 import S3Storage

logger = logging.getLogger(__name__)

SQS_BATCH_SIZE = 10
KST = timezone(timedelta(hours=9))


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"필수 환경변수 누락: {name}")
    return val


def _make_storage() -> S3Storage:
    return S3Storage(bucket=_required_env("S3_BUCKET"))


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
    """SQS 트리거. 공고 1건 상세 크롤링 → S3 저장."""
    storage = _make_storage()
    ocr_server_url = os.environ.get("OCR_SERVER_URL", "")
    ocr_api_key = os.environ.get("OCR_API_KEY", "")

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
            result = crawler.fetch_detail(ref)
            if result is None:
                logger.info("텍스트·이미지 모두 없음, 스킵: id=%s", ref.external_id)
                continue

            if isinstance(result, ImageJobDetail):
                detail = _process_image_jd(result, ocr_server_url, ocr_api_key)
                if detail is None:
                    continue
            else:
                detail = result

            document = build_document(detail.raw_text, detail.tech_stack)
            embedding = embed_text(document)
            storage.save(detail, embedding=embedding)
        except Exception:
            logger.exception("상세 크롤링 실패: id=%s", ref.external_id)
            raise

    return {"statusCode": 200}


def _process_image_jd(
    image_detail: ImageJobDetail, ocr_server_url: str, ocr_api_key: str = "",
) -> JobDetail | None:
    """이미지 JD 를 OCR 처리하여 JobDetail 로 변환."""
    if not ocr_server_url:
        logger.info("OCR_SERVER_URL 미설정, 이미지 JD 스킵: id=%s", image_detail.external_id)
        return None

    raw_text = call_ocr(list(image_detail.images_b64), ocr_server_url, ocr_api_key)
    if not raw_text.strip():
        logger.info("OCR 결과 비어있음, 스킵: id=%s", image_detail.external_id)
        return None

    cleaned = remove_noise_sections(raw_text)
    if not cleaned:
        logger.info("OCR 노이즈 제거 후 텍스트 없음, 스킵: id=%s", image_detail.external_id)
        return None

    logger.info("OCR 완료: id=%s, %d자", image_detail.external_id, len(cleaned))
    return JobDetail(
        source=image_detail.source,
        external_id=image_detail.external_id,
        url=image_detail.url,
        company_name=image_detail.company_name,
        title=image_detail.title,
        raw_text=cleaned,
        tech_stack=image_detail.tech_stack,
        deadline=image_detail.deadline,
        crawled_at=image_detail.crawled_at,
        career_level=image_detail.career_level,
    )
