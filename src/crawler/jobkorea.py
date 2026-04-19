"""잡코리아 크롤러. 동작 파라미터는 JOBKOREA_* 환경변수로 오버라이드 가능."""
import base64
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Callable, ClassVar, TypeVar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from crawler.base import (
    DEFAULT_DELAY_MAX,
    DEFAULT_DELAY_MIN,
    DEFAULT_MAX_PAGES,
    DEFAULT_STALE_PAGE_THRESHOLD,
    ImageJobDetail,
    JobCrawler,
    JobDetail,
    JobListingRef,
)
from parser.jobkorea import (
    extract_iframe_image_urls,
    parse_job_detail,
    parse_job_iframe,
    parse_job_list,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

BASE_URL = "https://www.jobkorea.co.kr"
LIST_URL = f"{BASE_URL}/recruit/joblist"
GI_LIST_URL = f"{LIST_URL}/_GI_List/"
DETAIL_URL = f"{BASE_URL}/Recruit/GI_Read"
IFRAME_URL = f"{BASE_URL}/Recruit/GI_Read_Comt_Ifrm"

USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.jobkorea.co.kr/",
}

DUTY_GROUP_CODE = "10031"

# 12개 개발 직무 카테고리. 환경변수 JOBKOREA_CATEGORY_CODES (콤마 구분) 로 오버라이드 가능.
_DEFAULT_CATEGORY_CODES: tuple[str, ...] = (
    "1000229",  # 백엔드개발자
    "1000230",  # 프론트엔드개발자
    "1000231",  # 웹개발자
    "1000232",  # 앱개발자
    "1000236",  # 데이터엔지니어
    "1000237",  # 데이터사이언티스트
    "1000239",  # 소프트웨어개발자
    "1000240",  # 게임개발자
    "1000242",  # AI/ML엔지니어
    "1000244",  # 클라우드엔지니어
    "1000422",  # MLOps엔지니어
    "1000423",  # AI서비스개발자
)

# 제목 제외 필터. 환경변수 JOBKOREA_EXCLUDE_KEYWORDS (콤마 구분) 로 오버라이드 가능.
_DEFAULT_EXCLUDE_KEYWORDS: tuple[str, ...] = (
    "교육생",
    "부트캠프",
    "bootcamp",
)


class JobKoreaCrawler(JobCrawler):
    source: ClassVar[str] = "jobkorea"

    def __init__(
        self,
        *,
        delay_min: float | None = None,
        delay_max: float | None = None,
        max_pages: int | None = None,
        stale_page_threshold: int | None = None,
        category_codes: tuple[str, ...] | None = None,
        exclude_keywords: tuple[str, ...] | None = None,
    ):
        super().__init__(
            delay_min=_resolve_env("JOBKOREA_DELAY_MIN", delay_min, DEFAULT_DELAY_MIN, float),
            delay_max=_resolve_env("JOBKOREA_DELAY_MAX", delay_max, DEFAULT_DELAY_MAX, float),
            max_pages=_resolve_env("JOBKOREA_MAX_PAGES", max_pages, DEFAULT_MAX_PAGES, int),
            stale_page_threshold=_resolve_env(
                "JOBKOREA_STALE_PAGE_THRESHOLD", stale_page_threshold, DEFAULT_STALE_PAGE_THRESHOLD, int,
            ),
            exclude_title_keywords=_resolve_tuple_env(
                "JOBKOREA_EXCLUDE_KEYWORDS", exclude_keywords, _DEFAULT_EXCLUDE_KEYWORDS,
            ),
        )
        self.category_codes = _resolve_tuple_env(
            "JOBKOREA_CATEGORY_CODES", category_codes, _DEFAULT_CATEGORY_CODES,
        )
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        headers = dict(BASE_HEADERS)
        headers["User-Agent"] = random.choice(USER_AGENTS)
        headers["X-Requested-With"] = "XMLHttpRequest"
        self.session.headers.update(headers)

    @classmethod
    def detail_url(cls, external_id: str) -> str:
        return f"{DETAIL_URL}/{external_id}"

    def fetch_listings_page(self, page: int) -> list[JobListingRef]:
        data = {
            "isDefault": "false",
            "condition[duty]": ",".join(self.category_codes),
            "condition[menucode]": "duty",
            "page": page,
            "direct": "0",
            "order": "3",  # 최신업데이트순
            "pagesize": "40",
            "tabindex": "0",
            "onePick": "0",
            "confirm": "0",
            "profile": "0",
        }
        resp = self.session.post(GI_LIST_URL, data=data, timeout=15)
        resp.raise_for_status()
        return [
            JobListingRef(
                source=self.source,
                external_id=item.job_id,
                url=self.detail_url(item.job_id),
                title=item.title,
                company_name=item.company_name,
                career_level=item.career_level,
            )
            for item in parse_job_list(resp.text)
        ]

    def fetch_detail(self, ref: JobListingRef) -> JobDetail | ImageJobDetail | None:
        # 상세 페이지 → 메타데이터 (회사명, 제목, 마감일, 기술스택)
        detail_resp = self.session.get(ref.url, timeout=15)
        detail_resp.raise_for_status()
        metadata = parse_job_detail(detail_resp.text)

        self._delay()

        # iframe → JD 본문 텍스트
        iframe_resp = self.session.get(IFRAME_URL, params={"Gno": ref.external_id}, timeout=15)
        iframe_resp.raise_for_status()
        raw_text = parse_job_iframe(iframe_resp.text)

        if raw_text is not None:
            return JobDetail(
                source=self.source,
                external_id=ref.external_id,
                url=ref.url,
                company_name=metadata.company_name or ref.company_name,
                title=metadata.title or ref.title,
                raw_text=raw_text,
                tech_stack=metadata.tech_stack,
                deadline=metadata.deadline,
                crawled_at=datetime.now(KST).isoformat(),
                career_level=ref.career_level,
            )

        # 이미지 JD: 이미지 다운로드 → ImageJobDetail 반환
        image_urls = extract_iframe_image_urls(iframe_resp.text)
        if not image_urls:
            logger.info("external_id=%s: 텍스트·이미지 모두 없음, 스킵", ref.external_id)
            return None

        images_b64 = self._download_images(image_urls)
        if not images_b64:
            logger.info("external_id=%s: 이미지 다운로드 실패, 스킵", ref.external_id)
            return None

        logger.info("external_id=%s: 이미지 JD %d장 추출", ref.external_id, len(images_b64))
        return ImageJobDetail(
            source=self.source,
            external_id=ref.external_id,
            url=ref.url,
            company_name=metadata.company_name or ref.company_name,
            title=metadata.title or ref.title,
            images_b64=tuple(images_b64),
            tech_stack=metadata.tech_stack,
            deadline=metadata.deadline,
            crawled_at=datetime.now(KST).isoformat(),
            career_level=ref.career_level,
        )

    def _download_images(self, urls: list[str]) -> list[str]:
        """이미지 URL 목록을 병렬 다운로드하여 base64 인코딩된 리스트로 반환."""
        from concurrent.futures import ThreadPoolExecutor

        def _fetch(url: str) -> str | None:
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                return base64.b64encode(resp.content).decode("ascii")
            except Exception:
                logger.warning("이미지 다운로드 실패: %s", url, exc_info=True)
                return None

        with ThreadPoolExecutor(max_workers=min(len(urls), 5)) as pool:
            fetched = pool.map(_fetch, urls)

        return [img for img in fetched if img is not None]


_T = TypeVar("_T")


def _resolve_env(env_name: str, override: _T | None, default: _T, parse: Callable[[str], _T]) -> _T:
    """우선순위: 명시적 override > 환경변수 > 기본값."""
    if override is not None:
        return override
    raw = os.environ.get(env_name)
    return parse(raw) if raw else default


def _resolve_tuple_env(env_name: str, override: tuple[str, ...] | None, default: tuple[str, ...]) -> tuple[str, ...]:
    """콤마 구분 환경변수를 tuple 로 해석."""
    if override is not None:
        return override
    raw = os.environ.get(env_name)
    if raw:
        return tuple(s.strip() for s in raw.split(",") if s.strip())
    return default
