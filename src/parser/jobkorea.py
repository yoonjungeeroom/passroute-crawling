"""잡코리아 HTML 파서 — 목록 / 상세 메타(__next_f) / iframe JD 텍스트 추출."""
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from parser.common import normalize_tech_name

# 텍스트 100자 미만 + <img> 존재 → 이미지 JD 로 판정
IMAGE_JD_TEXT_THRESHOLD = 100


@dataclass(frozen=True)
class JobkoreaMetadata:
    """상세 페이지 __next_f JSON 에서 뽑은 메타데이터."""
    company_name: str = ""
    title: str = ""
    deadline: str = ""
    tech_stack: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobkoreaListItem:
    """목록 페이지에서 추출한 공고 한 건의 기본 정보."""
    job_id: str
    title: str
    company_name: str


def parse_job_list(html: str) -> list[JobkoreaListItem]:
    """목록 페이지 HTML 에서 공고 기본 정보를 추출."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[JobkoreaListItem] = []

    for row in soup.select("table tbody tr"):
        link = row.select_one('a[href*="/Recruit/GI_Read/"]')
        if not link:
            continue
        match = re.search(r"/Recruit/GI_Read/(\d+)", link["href"])
        if not match:
            continue
        company_tag = row.select_one('a[href*="/Recruit/Co_Read/"]')
        jobs.append(JobkoreaListItem(
            job_id=match.group(1),
            title=link.get_text(strip=True),
            company_name=company_tag.get_text(strip=True) if company_tag else "",
        ))

    return jobs


def parse_job_detail(html: str) -> JobkoreaMetadata:
    """상세 페이지 __next_f JSON 에서 메타데이터 추출.

    __next_f 데이터는 이스케이프 상태이므로 unicode_escape 디코딩 없이
    원본 HTML 에서 직접 정규식으로 추출한다.
    """
    return JobkoreaMetadata(
        company_name=_match_escaped_json_string(html, "postingCompanyName"),
        title=_match_escaped_json_string(html, "title"),
        deadline=_match_escaped_json_string(html, "applicationEndAt"),
        tech_stack=tuple(_extract_tech_stack(html)),
    )


def parse_job_iframe(html: str) -> str | None:
    """iframe 에서 JD 텍스트 전체를 추출. 이미지 JD 면 None."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n", strip=True)

    if len(text) < IMAGE_JD_TEXT_THRESHOLD and soup.find_all("img"):
        return None

    return text or None


# ── 내부 헬퍼 ──


def _match_escaped_json_string(html: str, key: str) -> str:
    r"""이스케이프된 JSON `\"key\":\"VALUE\"` 에서 VALUE 추출."""
    pattern = r'\\"' + re.escape(key) + r'\\":\\"((?:[^\\]|\\\\.)*?)\\"'
    match = re.search(pattern, html)
    return match.group(1) if match else ""


def _extract_tech_stack(html: str) -> list[str]:
    """__next_f 에서 HARD_SKILL 기술스택을 추출·정규화·중복 제거."""
    normalized: list[str] = []
    seen: set[str] = set()

    pattern = (
        r'\\"name\\":\\"((?:[^\\]|\\\\.)*?)\\"'
        r',\\"rank\\":\d+'
        r',\\"manualInput\\":\w+'
        r',\\"skillTypeCode\\":\\"HARD_SKILL\\"'
    )
    for match in re.finditer(pattern, html):
        name = match.group(1)
        if not name or len(name) >= 30:
            continue
        canonical = normalize_tech_name(name)
        key = canonical.lower()
        if key not in seen:
            seen.add(key)
            normalized.append(canonical)

    return normalized
