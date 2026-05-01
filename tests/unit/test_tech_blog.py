"""tech_blog 수집 모듈 및 blog_collector Lambda 핸들러 단위 테스트."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from collector.tech_blog import (
    BLOG_RETENTION_DAYS,
    BlogArticle,
    BlogFeed,
    TechBlogCollector,
    _deadline_from_pub_date,
    _make_external_id,
    _strip_html,
    blog_article_to_detail_dict,
)

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────────────────
# 헬퍼 함수 테스트
# ─────────────────────────────────────────────────────────


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>hello <b>world</b></p>") == "hello world"

    def test_unescapes_entities(self):
        assert _strip_html("A &amp; B &lt;C&gt;") == "A & B <C>"

    def test_empty_string(self):
        assert _strip_html("") == ""


class TestMakeExternalId:
    def test_deterministic(self):
        url = "https://tech.kakao.com/post/123"
        assert _make_external_id(url) == _make_external_id(url)

    def test_length_12(self):
        assert len(_make_external_id("https://example.com")) == 12

    def test_different_urls_differ(self):
        assert _make_external_id("https://a.com") != _make_external_id("https://b.com")


class TestDeadlineFromPubDate:
    def test_adds_retention_days(self):
        pub = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = pub + timedelta(days=BLOG_RETENTION_DAYS)
        assert _deadline_from_pub_date(pub) == int(expected.timestamp())


# ─────────────────────────────────────────────────────────
# blog_article_to_detail_dict 변환 테스트
# ─────────────────────────────────────────────────────────


def _article(**overrides) -> BlogArticle:
    base = dict(
        company_name="카카오",
        title="Kafka 파티션 전략",
        summary="대규모 트래픽 환경에서의 Kafka 파티션 최적화 사례를 공유합니다.",
        url="https://tech.kakao.com/post/123",
        pub_date=datetime(2026, 3, 15, 10, 0, tzinfo=KST),
        collected_at="2026-05-02T10:00:00+09:00",
    )
    base.update(overrides)
    return BlogArticle(**base)


class TestBlogArticleToDetailDict:
    def test_source_is_tech_blog(self):
        data = blog_article_to_detail_dict(_article())
        assert data["source"] == "tech_blog"

    def test_raw_text_combines_title_and_summary(self):
        data = blog_article_to_detail_dict(_article())
        assert data["raw_text"].startswith("Kafka 파티션 전략")
        assert "대규모 트래픽" in data["raw_text"]

    def test_raw_text_title_only_when_no_summary(self):
        data = blog_article_to_detail_dict(_article(summary=""))
        assert data["raw_text"] == "Kafka 파티션 전략"

    def test_deadline_is_unix_timestamp(self):
        data = blog_article_to_detail_dict(_article())
        assert isinstance(data["deadline"], int)
        assert data["deadline"] > 0

    def test_tech_stack_empty(self):
        data = blog_article_to_detail_dict(_article())
        assert data["tech_stack"] == []

    def test_career_level_empty(self):
        data = blog_article_to_detail_dict(_article())
        assert data["career_level"] == ""


# ─────────────────────────────────────────────────────────
# TechBlogCollector 테스트
# ─────────────────────────────────────────────────────────


def _mock_feed_result(entries):
    """feedparser.parse 의 반환값을 흉내내는 객체."""
    result = MagicMock()
    result.bozo = False
    result.entries = entries
    return result


def _feed_entry(title="테스트 글", url="https://blog.test/1", summary="요약"):
    return {
        "title": title,
        "link": url,
        "summary": summary,
        "published": "Sat, 01 Mar 2026 10:00:00 +0900",
    }


class TestTechBlogCollector:
    @patch("collector.tech_blog.feedparser.parse")
    @patch("collector.tech_blog.time.sleep")
    def test_collect_all_deduplicates_by_url(self, mock_sleep, mock_parse):
        """동일 URL 이 여러 피드에 있어도 1건만 수집."""
        same_url = "https://blog.test/shared"
        mock_parse.return_value = _mock_feed_result([
            _feed_entry(url=same_url),
        ])

        feeds = (
            BlogFeed("A사", "https://a.com/feed"),
            BlogFeed("B사", "https://b.com/feed"),
        )
        collector = TechBlogCollector(feeds=feeds, request_delay=0)
        articles = collector.collect_all()

        assert len(articles) == 1
        assert articles[0].url == same_url

    @patch("collector.tech_blog.feedparser.parse")
    @patch("collector.tech_blog.time.sleep")
    def test_collect_all_skips_entries_without_link(self, mock_sleep, mock_parse):
        """link 가 없는 항목은 스킵."""
        mock_parse.return_value = _mock_feed_result([
            {"title": "제목만", "summary": "요약"},
            _feed_entry(title="정상 글", url="https://blog.test/ok"),
        ])

        feeds = (BlogFeed("테스트", "https://test.com/feed"),)
        collector = TechBlogCollector(feeds=feeds, request_delay=0)
        articles = collector.collect_all()

        assert len(articles) == 1

    @patch("collector.tech_blog.feedparser.parse")
    @patch("collector.tech_blog.time.sleep")
    def test_collect_all_skips_entries_without_summary(self, mock_sleep, mock_parse):
        """요약이 없는 항목은 스킵."""
        mock_parse.return_value = _mock_feed_result([
            _feed_entry(title="요약 없음", url="https://blog.test/no-summary", summary=""),
            _feed_entry(title="정상 글", url="https://blog.test/ok", summary="요약 있음"),
        ])

        feeds = (BlogFeed("테스트", "https://test.com/feed"),)
        collector = TechBlogCollector(feeds=feeds, request_delay=0)
        articles = collector.collect_all()

        assert len(articles) == 1
        assert articles[0].title == "정상 글"

    @patch("collector.tech_blog.feedparser.parse")
    @patch("collector.tech_blog.time.sleep")
    def test_collect_all_handles_feed_error(self, mock_sleep, mock_parse):
        """피드 파싱 예외 시 해당 피드를 스킵하고 계속 진행."""
        mock_parse.side_effect = Exception("network error")

        feeds = (BlogFeed("에러피드", "https://error.com/feed"),)
        collector = TechBlogCollector(feeds=feeds, request_delay=0)
        articles = collector.collect_all()

        assert articles == []


# ─────────────────────────────────────────────────────────
# blog_collector Lambda 핸들러 테스트
# ─────────────────────────────────────────────────────────


class TestBlogCollectorHandler:
    @patch("embedding.embed_text", return_value=[0.1] * 768)
    @patch("app.S3Storage")
    @patch("app.TechBlogCollector")
    def test_saves_new_articles(self, mock_collector_cls, mock_storage_cls, mock_embed):
        """신규 블로그 글이 S3 에 저장된다."""
        import app

        mock_storage = MagicMock()
        mock_storage.get_all_urls.return_value = set()
        mock_storage_cls.return_value = mock_storage

        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [_article()]
        mock_collector_cls.return_value = mock_collector

        result = app.blog_collector({}, None)

        body = json.loads(result["body"])
        assert body["saved"] == 1
        assert body["skipped"] == 0
        mock_storage.s3.put_object.assert_called_once()

    @patch("embedding.embed_text", return_value=[0.1] * 768)
    @patch("app.S3Storage")
    @patch("app.TechBlogCollector")
    def test_skips_existing_urls(self, mock_collector_cls, mock_storage_cls, mock_embed):
        """이미 저장된 URL 은 스킵한다."""
        import app

        mock_storage = MagicMock()
        mock_storage.get_all_urls.return_value = {"https://tech.kakao.com/post/123"}
        mock_storage_cls.return_value = mock_storage

        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [_article()]
        mock_collector_cls.return_value = mock_collector

        result = app.blog_collector({}, None)

        body = json.loads(result["body"])
        assert body["saved"] == 0
        assert body["skipped"] == 1
        mock_storage.s3.put_object.assert_not_called()

    @patch("embedding.embed_text", side_effect=RuntimeError("model error"))
    @patch("app.S3Storage")
    @patch("app.TechBlogCollector")
    def test_saves_without_embedding_on_failure(
        self, mock_collector_cls, mock_storage_cls, mock_embed,
    ):
        """임베딩 실패 시에도 임베딩 없이 S3 에 저장한다."""
        import app

        mock_storage = MagicMock()
        mock_storage.get_all_urls.return_value = set()
        mock_storage_cls.return_value = mock_storage

        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [_article()]
        mock_collector_cls.return_value = mock_collector

        result = app.blog_collector({}, None)

        body = json.loads(result["body"])
        assert body["saved"] == 1
        mock_storage.s3.put_object.assert_called_once()
        saved_body = json.loads(
            mock_storage.s3.put_object.call_args.kwargs["Body"].decode("utf-8")
        )
        assert "embedding" not in saved_body
