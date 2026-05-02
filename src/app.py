"""passroute-crawler Lambda 핸들러.

EventBridge cron → [job_list_collector] → SQS → [job_detail_crawler] → S3 → EC2 consumer → ChromaDB
EventBridge cron → [news_collector] → S3 → EC2 consumer → ChromaDB
EventBridge cron → [blog_collector] → S3 → EC2 consumer → ChromaDB
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

from collector.naver_news import NaverNewsCollector, news_item_to_detail_dict
from crawler.base import ImageJobDetail, JobDetail, JobListingRef
from crawler.registry import get_crawler, iter_sources
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

    delete_requested = storage.delete_expired(datetime.now(KST).isoformat())
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
        "body": json.dumps({"new": total_new, "delete_requested": delete_requested}),
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
    from embedding import build_document, embed_text  # noqa: C0415

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
            result = crawler.fetch_detail(ref)
            if result is None:
                logger.info("텍스트·이미지 모두 없음, 스킵: id=%s", ref.external_id)
                continue

            if isinstance(result, ImageJobDetail):
                detail = _process_image_jd(result)
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


# ── Lambda 3: 뉴스 수집 (cron) ──


def news_collector(event, context):
    """주요 기업의 기술/사업 동향 뉴스를 수집하여 S3 에 저장."""
    from embedding import build_document, embed_text  # noqa: C0415

    client_id = _required_env("NAVER_CLIENT_ID")
    client_secret = _required_env("NAVER_CLIENT_SECRET")
    storage = _make_storage()

    existing_urls = storage.get_all_urls()

    collector = NaverNewsCollector(client_id=client_id, client_secret=client_secret)
    items = collector.collect_all()

    saved = 0
    skipped = 0
    for item in items:
        if item.url in existing_urls:
            skipped += 1
            continue

        data = news_item_to_detail_dict(item)

        try:
            document = build_document(data["raw_text"], tuple(data["tech_stack"]))
            embedding = embed_text(document)
            data["embedding"] = embedding
        except Exception:
            logger.exception("임베딩 실패, 임베딩 없이 저장: id=%s", data["external_id"])

        key = f"parsed/{data['source']}/{data['external_id']}.json"
        storage.s3.put_object(
            Bucket=storage.bucket,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        )
        saved += 1

    logger.info("뉴스 수집 완료: 저장 %d건, 중복 스킵 %d건", saved, skipped)
    return {
        "statusCode": 200,
        "body": json.dumps({"saved": saved, "skipped": skipped}),
    }


# ── Lambda 4: 기술 블로그 수집 (cron) ──


BLOG_BATCH_SIZE = int(os.environ.get("BLOG_BATCH_SIZE", "100"))


def blog_collector(event, context):
    """주요 기업 기술 블로그 RSS 피드를 수집하여 S3 에 저장."""
    from collector.tech_blog import TechBlogCollector, blog_article_to_detail_dict  # noqa: C0415
    from embedding import build_document, embed_text  # noqa: C0415

    storage = _make_storage()
    existing_urls = storage.get_all_urls()

    collector = TechBlogCollector()
    articles = collector.collect_all()

    new_articles = [a for a in articles if a.url not in existing_urls][:BLOG_BATCH_SIZE]
    skipped = len(articles) - len(new_articles)
    del articles

    saved = 0
    for article in new_articles:
        data = blog_article_to_detail_dict(article)

        try:
            document = build_document(data["raw_text"], tuple(data["tech_stack"]))
            embedding = embed_text(document)
            data["embedding"] = embedding
        except Exception:
            logger.exception("임베딩 실패, 임베딩 없이 저장: id=%s", data["external_id"])

        key = f"parsed/{data['source']}/{data['external_id']}.json"
        storage.s3.put_object(
            Bucket=storage.bucket,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        )
        saved += 1

    logger.info("블로그 수집 완료: 저장 %d건, 중복 스킵 %d건", saved, skipped)
    return {
        "statusCode": 200,
        "body": json.dumps({"saved": saved, "skipped": skipped}),
    }


def _process_image_jd(image_detail: ImageJobDetail) -> JobDetail | None:
    """이미지 JD 를 로컬 ONNX OCR 로 처리하여 JobDetail 로 변환."""
    from ocr_client import call_ocr  # noqa: C0415
    from parser.jobkorea import remove_noise_sections  # noqa: C0415

    raw_text = call_ocr(list(image_detail.images_b64))
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
