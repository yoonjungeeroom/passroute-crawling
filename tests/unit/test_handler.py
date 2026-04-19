"""app.py 의 Lambda 핸들러 2개에 대한 단위 테스트.

외부 I/O(SQS, S3, 크롤러)는 전부 mock 으로 대체한다.
크롤러는 ``app.get_crawler`` 를 패치하여 source 문자열에 무관하게 같은 mock 을 돌려주도록 한다.

테스트는 "한 케이스 = 한 동작" 원칙으로 작성한다. 배치 크기 같은 구현 세부 수치에는
의존하지 않고 "신규 공고만 전송되었는가?" 같은 외부 관찰 가능한 동작만 검증한다.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

import app
from crawler.base import ImageJobDetail, JobDetail, JobListingRef


# ─────────────────────────────────────────────────────────
# 공용 헬퍼
# ─────────────────────────────────────────────────────────


def _make_sqs_event(body: dict) -> dict:
    return {"Records": [{"body": json.dumps(body)}]}


def _ref(external_id: str, company: str, title: str) -> JobListingRef:
    return JobListingRef(
        source="jobkorea",
        external_id=external_id,
        url=f"https://www.jobkorea.co.kr/Recruit/GI_Read/{external_id}",
        title=title,
        company_name=company,
    )


def _collect_sent_messages(mock_sqs) -> list[dict]:
    """send_message_batch 로 전송된 모든 메시지 본문을 한 리스트로 모은다."""
    sent: list[dict] = []
    for call in mock_sqs.send_message_batch.call_args_list:
        for entry in call.kwargs["Entries"]:
            sent.append(json.loads(entry["MessageBody"]))
    return sent


def _detail(**overrides) -> JobDetail:
    base = dict(
        source="jobkorea",
        external_id="999",
        url="https://www.jobkorea.co.kr/Recruit/GI_Read/999",
        company_name="패스루트",
        title="백엔드 채용",
        raw_text="주요업무: 백엔드 개발\n자격요건: Python 3년",
        tech_stack=("Python", "AWS"),
        deadline="2026-05-01T23:59:59+09:00",
        crawled_at="2026-04-11T18:00:00+09:00",
    )
    base.update(overrides)
    return JobDetail(**base)


# ─────────────────────────────────────────────────────────
# job_list_collector
# ─────────────────────────────────────────────────────────


@patch("app.boto3.client")
@patch("app.S3Storage")
@patch("app.get_crawler")
def test_job_list_collector_dispatches_only_new_jobs(
    mock_get_crawler, mock_storage_cls, mock_boto_client
):
    """S3 URL 인덱스에 없는 신규 공고만 JobDetailQueue 로 전송되어야 한다."""
    mock_sqs = MagicMock()
    mock_boto_client.return_value = mock_sqs

    mock_storage = MagicMock()
    mock_storage.delete_expired.return_value = True
    mock_storage.get_all_urls.return_value = {
        "https://www.jobkorea.co.kr/Recruit/GI_Read/111",
        "https://www.jobkorea.co.kr/Recruit/GI_Read/222",
    }
    mock_storage_cls.return_value = mock_storage

    mock_crawler = MagicMock()
    mock_crawler.collect_listings.return_value = [
        _ref("111", "A", "t1"),
        _ref("222", "B", "t2"),
        _ref("333", "C", "t3"),
    ]
    mock_get_crawler.return_value = mock_crawler

    app.job_list_collector({}, None)

    sent = _collect_sent_messages(mock_sqs)
    assert [m["external_id"] for m in sent] == ["333"]
    assert sent[0]["url"] == "https://www.jobkorea.co.kr/Recruit/GI_Read/333"
    assert sent[0]["source"] == "jobkorea"


@patch("app.boto3.client")
@patch("app.S3Storage")
@patch("app.get_crawler")
def test_job_list_collector_deletes_expired_before_dispatch(
    mock_get_crawler, mock_storage_cls, mock_boto_client
):
    """목록 수집 전에 마감 공고 삭제가 한 번 호출되어야 한다."""
    mock_boto_client.return_value = MagicMock()
    mock_storage = MagicMock()
    mock_storage.delete_expired.return_value = True
    mock_storage.get_all_urls.return_value = set()
    mock_storage_cls.return_value = mock_storage
    mock_crawler = MagicMock()
    mock_crawler.collect_listings.return_value = []
    mock_get_crawler.return_value = mock_crawler

    app.job_list_collector({}, None)

    mock_storage.delete_expired.assert_called_once()


@patch("app.boto3.client")
@patch("app.S3Storage")
@patch("app.get_crawler")
def test_job_list_collector_sends_nothing_when_all_existing(
    mock_get_crawler, mock_storage_cls, mock_boto_client
):
    """수집된 모든 공고가 이미 저장되어 있으면 SQS 전송이 일어나지 않는다."""
    mock_sqs = MagicMock()
    mock_boto_client.return_value = mock_sqs

    mock_storage = MagicMock()
    mock_storage.delete_expired.return_value = True
    mock_storage.get_all_urls.return_value = {
        "https://www.jobkorea.co.kr/Recruit/GI_Read/111",
    }
    mock_storage_cls.return_value = mock_storage

    mock_crawler = MagicMock()
    mock_crawler.collect_listings.return_value = [_ref("111", "A", "t1")]
    mock_get_crawler.return_value = mock_crawler

    app.job_list_collector({}, None)

    mock_sqs.send_message_batch.assert_not_called()


@patch("app.boto3.client")
@patch("app.S3Storage")
@patch("app.get_crawler")
def test_job_list_collector_returns_counts_in_body(
    mock_get_crawler, mock_storage_cls, mock_boto_client
):
    """응답 body 에 신규 전송 건수와 삭제 건수가 포함되어야 한다."""
    mock_boto_client.return_value = MagicMock()
    mock_storage = MagicMock()
    mock_storage.delete_expired.return_value = True
    mock_storage.get_all_urls.return_value = set()
    mock_storage_cls.return_value = mock_storage
    mock_crawler = MagicMock()
    mock_crawler.collect_listings.return_value = [_ref("100", "X", "t")]
    mock_get_crawler.return_value = mock_crawler

    result = app.job_list_collector({}, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"new": 1, "delete_requested": True}


@patch("app.boto3.client")
@patch("app.S3Storage")
def test_job_list_collector_fails_fast_when_queue_url_missing(
    mock_storage_cls, mock_boto_client, monkeypatch
):
    """필수 환경변수 JOB_DETAIL_QUEUE_URL 이 없으면 핸들러 진입 시 RuntimeError."""
    mock_boto_client.return_value = MagicMock()
    mock_storage_cls.return_value = MagicMock()
    monkeypatch.delenv("JOB_DETAIL_QUEUE_URL", raising=False)

    with pytest.raises(RuntimeError, match="JOB_DETAIL_QUEUE_URL"):
        app.job_list_collector({}, None)


# ─────────────────────────────────────────────────────────
# job_detail_crawler
# ─────────────────────────────────────────────────────────


@patch("embedding.embed_text", return_value=[0.1] * 768)
@patch("app.S3Storage")
@patch("app.get_crawler")
def test_job_detail_crawler_saves_fetched_detail(
    mock_get_crawler, mock_storage_cls, mock_embed,
):
    """상세 크롤링 성공 시 storage.save 가 임베딩과 함께 호출되어야 한다."""
    mock_storage = MagicMock()
    mock_storage_cls.return_value = mock_storage

    mock_crawler = MagicMock()
    mock_crawler.fetch_detail.return_value = _detail()
    mock_get_crawler.return_value = mock_crawler

    event = _make_sqs_event({
        "source": "jobkorea",
        "external_id": "999",
        "url": "https://www.jobkorea.co.kr/Recruit/GI_Read/999",
        "company_name": "패스루트",
        "title": "백엔드 채용",
    })
    app.job_detail_crawler(event, None)

    mock_storage.save.assert_called_once()
    saved = mock_storage.save.call_args.args[0]
    assert isinstance(saved, JobDetail)
    assert mock_storage.save.call_args.kwargs["embedding"] == [0.1] * 768


@patch("app.S3Storage")
@patch("app.get_crawler")
def test_job_detail_crawler_skips_when_fetch_returns_none(
    mock_get_crawler, mock_storage_cls
):
    """fetch_detail 이 None 을 반환하면(이미지 JD 등) 저장하지 않고 스킵한다."""
    mock_storage = MagicMock()
    mock_storage_cls.return_value = mock_storage

    mock_crawler = MagicMock()
    mock_crawler.fetch_detail.return_value = None
    mock_get_crawler.return_value = mock_crawler

    event = _make_sqs_event({
        "source": "jobkorea",
        "external_id": "999",
        "url": "https://www.jobkorea.co.kr/Recruit/GI_Read/999",
        "company_name": "A",
        "title": "t",
    })
    app.job_detail_crawler(event, None)

    mock_storage.save.assert_not_called()


@patch("app.S3Storage")
@patch("app.get_crawler")
def test_job_detail_crawler_reraises_on_failure(mock_get_crawler, mock_storage_cls):
    """크롤링 예외 발생 시 SQS 재시도를 위해 예외가 다시 던져져야 한다."""
    mock_storage_cls.return_value = MagicMock()

    mock_crawler = MagicMock()
    mock_crawler.fetch_detail.side_effect = RuntimeError("boom")
    mock_get_crawler.return_value = mock_crawler

    event = _make_sqs_event({
        "source": "jobkorea",
        "external_id": "999",
        "url": "https://www.jobkorea.co.kr/Recruit/GI_Read/999",
        "company_name": "A",
        "title": "t",
    })

    with pytest.raises(RuntimeError, match="boom"):
        app.job_detail_crawler(event, None)


# ─────────────────────────────────────────────────────────
# job_detail_crawler — 이미지 JD OCR 처리
# ─────────────────────────────────────────────────────────


def _image_detail(**overrides) -> ImageJobDetail:
    base = dict(
        source="jobkorea",
        external_id="888",
        url="https://www.jobkorea.co.kr/Recruit/GI_Read/888",
        company_name="이미지기업",
        title="프론트엔드 채용",
        images_b64=("aW1hZ2VkYXRh",),
        tech_stack=("React",),
        deadline="2026-05-01T23:59:59+09:00",
        crawled_at="2026-04-11T18:00:00+09:00",
    )
    base.update(overrides)
    return ImageJobDetail(**base)


@patch("embedding.embed_text", return_value=[0.1] * 768)
@patch("ocr_client.call_ocr", return_value="담당업무\n프론트엔드 개발\n자격요건\nReact 경험")
@patch("app.S3Storage")
@patch("app.get_crawler")
def test_image_jd_ocr_saves_detail(
    mock_get_crawler, mock_storage_cls, mock_ocr, mock_embed,
):
    """이미지 JD 가 OCR 처리되어 JobDetail 로 저장된다."""
    mock_storage = MagicMock()
    mock_storage_cls.return_value = mock_storage

    mock_crawler = MagicMock()
    mock_crawler.fetch_detail.return_value = _image_detail()
    mock_get_crawler.return_value = mock_crawler

    event = _make_sqs_event({
        "source": "jobkorea",
        "external_id": "888",
        "url": "https://www.jobkorea.co.kr/Recruit/GI_Read/888",
        "company_name": "이미지기업",
        "title": "프론트엔드 채용",
    })
    app.job_detail_crawler(event, None)

    mock_ocr.assert_called_once()
    mock_storage.save.assert_called_once()
    saved = mock_storage.save.call_args.args[0]
    assert isinstance(saved, JobDetail)
    assert "프론트엔드 개발" in saved.raw_text


@patch("embedding.embed_text", return_value=[0.1] * 768)
@patch("ocr_client.call_ocr", return_value="")
@patch("app.S3Storage")
@patch("app.get_crawler")
def test_image_jd_skipped_when_ocr_empty(
    mock_get_crawler, mock_storage_cls, mock_ocr, mock_embed,
):
    """OCR 결과가 비어있으면 저장하지 않고 스킵한다."""
    mock_storage = MagicMock()
    mock_storage_cls.return_value = mock_storage

    mock_crawler = MagicMock()
    mock_crawler.fetch_detail.return_value = _image_detail()
    mock_get_crawler.return_value = mock_crawler

    event = _make_sqs_event({
        "source": "jobkorea",
        "external_id": "888",
        "url": "https://www.jobkorea.co.kr/Recruit/GI_Read/888",
        "company_name": "이미지기업",
        "title": "프론트엔드 채용",
    })
    app.job_detail_crawler(event, None)

    mock_storage.save.assert_not_called()
