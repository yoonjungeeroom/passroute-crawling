"""주요 IT 기업 기술 블로그 RSS 피드 수집 모듈.

22개 RSS/Atom 피드로 기술 블로그 글을 수집하여 면접 질문 생성에 활용한다.
"""
import hashlib
import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

BLOG_RETENTION_DAYS = 730
_FEED_FILTER_DAYS = timedelta(days=730)

# ── 블로그 피드 설정 ──


@dataclass(frozen=True)
class BlogFeed:
    """RSS/Atom 피드 1개."""
    company_name: str
    feed_url: str


_DEFAULT_FEEDS: tuple[BlogFeed, ...] = (
    BlogFeed("네이버", "https://d2.naver.com/d2.atom"),
    BlogFeed("카카오", "https://tech.kakao.com/feed"),
    BlogFeed("카카오페이", "https://tech.kakaopay.com/rss.xml"),
    BlogFeed("카카오뱅크", "https://tech.kakaobank.com/index.xml"),
    BlogFeed("토스", "https://toss.tech/rss.xml"),
    BlogFeed("우아한형제들", "https://techblog.woowahan.com/feed"),
    BlogFeed("당근", "https://medium.com/feed/daangn"),
    BlogFeed("쿠팡", "https://medium.com/feed/coupang-engineering"),
    BlogFeed("라인", "https://techblog.lycorp.co.jp/ko/feed/index.xml"),
    BlogFeed("삼성전자", "https://techblog.samsung.com/rss"),
    BlogFeed("LG U+", "https://techblog.uplus.co.kr/feed"),
    BlogFeed("KT Cloud", "https://tech.ktcloud.com/feed"),
    BlogFeed("NHN", "https://meetup.nhncloud.com/rss"),
    BlogFeed("마켓컬리", "https://helloworld.kurly.com/rss.xml"),
    BlogFeed("올리브영", "https://oliveyoung.tech/rss.xml"),
    BlogFeed("무신사", "https://medium.com/feed/musinsa-tech"),
    BlogFeed("뱅크샐러드", "https://blog.banksalad.com/rss.xml"),
    BlogFeed("야놀자", "https://medium.com/feed/yanoljacloud-tech"),
    BlogFeed("쏘카", "https://tech.socarcorp.kr/feed.xml"),
    BlogFeed("넷마블", "https://netmarble.engineering/feed/"),
    BlogFeed("지마켓", "https://dev.gmarket.com/rss"),
    BlogFeed("11번가", "https://11st-tech.github.io/rss/"),
)

# ── 피드 요청 간격 (초) ──

_DEFAULT_REQUEST_DELAY = 0.5


@dataclass(frozen=True)
class BlogArticle:
    """블로그 글 1건."""
    company_name: str
    title: str
    summary: str
    url: str
    pub_date: datetime
    collected_at: str


def _strip_html(text: str) -> str:
    """HTML 태그와 엔티티를 제거한다."""
    cleaned = re.sub(r"<[^>]+>", "", text)
    return html.unescape(cleaned).strip()


def _parse_pub_date(entry: dict) -> datetime:
    """feedparser 엔트리에서 발행일을 추출한다."""
    published = entry.get("published") or entry.get("updated") or ""
    if not published:
        return datetime.now(KST)
    try:
        return parsedate_to_datetime(published)
    except (ValueError, TypeError):
        pass
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            from calendar import timegm
            return datetime.fromtimestamp(timegm(entry.published_parsed), tz=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        pass
    return datetime.now(KST)


def _make_external_id(url: str) -> str:
    """URL 에서 결정적 external_id 를 생성."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _deadline_from_pub_date(pub_date: datetime) -> int:
    """pub_date + 730일을 Unix timestamp 로 변환."""
    expiry = pub_date + timedelta(days=BLOG_RETENTION_DAYS)
    return int(expiry.timestamp())


class TechBlogCollector:
    """RSS/Atom 피드를 사용해 기업 기술 블로그 글을 수집한다."""

    def __init__(
        self,
        *,
        feeds: tuple[BlogFeed, ...] | None = None,
        request_delay: float = _DEFAULT_REQUEST_DELAY,
    ):
        self.feeds = feeds or _DEFAULT_FEEDS
        self.request_delay = request_delay

    def _fetch_feed(self, feed: BlogFeed) -> list[BlogArticle]:
        """한 피드의 글을 수집한다."""
        now_iso = datetime.now(KST).isoformat()
        now = datetime.now(KST)

        try:
            parsed = feedparser.parse(feed.feed_url)
        except Exception:
            logger.exception("피드 파싱 실패: %s (%s)", feed.company_name, feed.feed_url)
            return []

        if parsed.bozo and not parsed.entries:
            logger.warning(
                "피드 오류 (항목 없음): %s (%s) — %s",
                feed.company_name, feed.feed_url, parsed.bozo_exception,
            )
            return []

        entries = parsed.entries

        # 20건 초과 피드는 최근 2년 이내 글만
        if len(entries) > 20:
            cutoff = now - _FEED_FILTER_DAYS
            entries = [
                e for e in entries
                if _parse_pub_date(e) >= cutoff
            ]

        articles: list[BlogArticle] = []
        for entry in entries:
            url = entry.get("link", "")
            if not url:
                continue

            title = _strip_html(entry.get("title", ""))
            if not title:
                continue

            summary_raw = entry.get("summary") or entry.get("description") or ""
            summary = _strip_html(summary_raw)

            if not summary:
                continue

            articles.append(BlogArticle(
                company_name=feed.company_name,
                title=title,
                summary=summary,
                url=url,
                pub_date=_parse_pub_date(entry),
                collected_at=now_iso,
            ))

        return articles

    def collect_all(self) -> list[BlogArticle]:
        """전체 피드에서 블로그 글을 수집한다. URL 기준 전역 중복 제거."""
        all_articles: list[BlogArticle] = []
        global_seen_urls: set[str] = set()

        for feed in self.feeds:
            articles = self._fetch_feed(feed)
            for article in articles:
                if article.url in global_seen_urls:
                    continue
                global_seen_urls.add(article.url)
                all_articles.append(article)

            logger.info("feed=%s: %d건 수집", feed.company_name, len(articles))

            time.sleep(self.request_delay)

        logger.info(
            "전체 블로그 수집 완료: %d건 (피드 %d개)",
            len(all_articles), len(self.feeds),
        )
        return all_articles


def blog_article_to_detail_dict(article: BlogArticle) -> dict:
    """BlogArticle 을 S3 저장용 dict 로 변환. JobDetail 호환 형식."""
    raw_text = f"{article.title}\n\n{article.summary}" if article.summary else article.title
    return {
        "source": "tech_blog",
        "external_id": _make_external_id(article.url),
        "url": article.url,
        "company_name": article.company_name,
        "title": article.title,
        "raw_text": raw_text,
        "tech_stack": [],
        "deadline": _deadline_from_pub_date(article.pub_date),
        "crawled_at": article.collected_at,
        "career_level": "",
    }
