"""잡코리아 HTML 파서 — 목록 / 상세 메타(__next_f) / iframe JD 텍스트 추출."""
import re
from dataclasses import dataclass
from urllib.parse import urljoin

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
    career_level: str = ""


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
        career_level = ""
        etc_tag = row.select_one("p.etc")
        if etc_tag:
            first_cell = etc_tag.select_one("span.cell")
            if first_cell:
                career_level = first_cell.get_text(strip=True)
        jobs.append(JobkoreaListItem(
            job_id=match.group(1),
            title=link.get_text(strip=True),
            company_name=company_tag.get_text(strip=True) if company_tag else "",
            career_level=career_level,
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
    """iframe 에서 JD 텍스트를 추출하고 노이즈 섹션을 제거. 이미지 JD 면 None."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n", strip=True)

    if len(text) < IMAGE_JD_TEXT_THRESHOLD and soup.find_all("img"):
        return None

    if not text:
        return None

    cleaned = remove_noise_sections(text)
    return cleaned or None


_IFRAME_BASE_URL = "https://www.jobkorea.co.kr/Recruit/GI_Read_Comt_Ifrm"

# 로고·아이콘 등 JD 본문과 무관한 작은 이미지를 걸러내는 최소 크기 (px).
_MIN_IMAGE_DIMENSION = 50


def extract_iframe_image_urls(html: str) -> list[str]:
    """iframe HTML 에서 JD 본문 이미지 URL 을 추출.

    data: URI, 너무 작은 이미지(로고·아이콘)는 제외한다.
    상대 경로는 잡코리아 iframe base URL 기준으로 절대 경로로 변환한다.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:"):
            continue

        if _is_small_image(img):
            continue

        absolute_url = urljoin(_IFRAME_BASE_URL, src)
        urls.append(absolute_url)

    return urls


def _is_small_image(img) -> bool:
    """width 또는 height 속성이 명시되어 있고 _MIN_IMAGE_DIMENSION 미만이면 True."""
    for attr in ("width", "height"):
        val = img.get(attr, "")
        try:
            if int(val) < _MIN_IMAGE_DIMENSION:
                return True
        except (ValueError, TypeError):
            continue
    return False


# ── 내부 헬퍼 ──


# JD 본문 시작을 나타내는 키워드.
# iframe 상단의 기업소개 노이즈를 건너뛰기 위해 사용한다.
_JD_START_HEADERS: frozenset[str] = frozenset({
    "모집분야", "모집부문", "모집공고",
    "담당업무", "주요업무", "업무내용", "주요직무",
    "자격요건", "지원자격", "필수요건",
    "우대사항", "우대요건",
})

# 노이즈 섹션 시작 키워드. 해당 줄부터 끝까지 제거한다.
# 잡코리아 iframe 하단에 복리후생·전형절차·접수정보가 반복적으로 붙는 패턴.
_NOISE_SECTION_HEADERS: frozenset[str] = frozenset({
    # 복리후생 블록
    "복리후생",
    # 전형·접수 블록
    "전형절차", "채용절차",
    "제출서류",
    "접수기간 및 방법", "접수기간", "접수방법",
    # 기업 소개 블록
    "기업정보", "기업 개요",
})


def remove_noise_sections(text: str) -> str:
    """기업소개·복리후생·전형절차 등 노이즈 섹션을 제거.

    1) JD 본문 시작 키워드(모집분야/담당업무 등)를 찾아 그 앞의 상단 노이즈를 제거한다.
    2) 노이즈 섹션 키워드(복리후생/전형절차 등)를 찾아 그 뒤의 하단 노이즈를 제거한다.
    두 전략을 결합하여 JD 본문 영역만 남긴다.
    """
    lines = text.split("\n")

    # 상단 노이즈 제거: JD 시작 키워드가 나올 때까지 건너뛰기
    start_index = 0
    for i, line in enumerate(lines):
        if line.strip() in _JD_START_HEADERS:
            start_index = i
            break

    # 하단 노이즈 제거: JD 본문 이후 노이즈 헤더부터 끝까지 잘라내기
    end_index = len(lines)
    for i in range(start_index, len(lines)):
        if lines[i].strip() in _NOISE_SECTION_HEADERS:
            end_index = i
            break

    result = "\n".join(lines[start_index:end_index]).strip()
    return result


def _match_escaped_json_string(html: str, key: str) -> str:
    r"""이스케이프된 JSON `\"key\":\"VALUE\"` 에서 VALUE 추출."""
    pattern = r'\\"' + re.escape(key) + r'\\":\\"((?:[^\\]|\\\\.)*?)\\"'
    match = re.search(pattern, html)
    return match.group(1) if match else ""


def _extract_tech_stack(html: str) -> list[str]:
    """__next_f 에서 HARD_SKILL 기술스택을 추출·정규화·중복 제거.

    잡코리아가 자격증·어학·비기술 항목도 HARD_SKILL 로 분류하므로
    패턴 매칭으로 제외한다.
    """
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
        if _is_non_tech_skill(name):
            continue
        canonical = normalize_tech_name(name)
        key = canonical.lower()
        if key not in seen:
            seen.add(key)
            normalized.append(canonical)

    return normalized


# 자격증 패턴: "~기사 자격", "~기능사 자격", "~관리사 자격" 등
_CERT_PATTERN = re.compile(
    r"(기사|기능사|관리사|산업기사)\s*자격$"
)

# 어학·비기술 항목 (소문자 비교)
_NON_TECH_NAMES: frozenset[str] = frozenset({
    # 어학
    "영어", "일본어", "중국어", "한국어",
    "비즈니스영어", "비즈니스일본어", "비즈니스중국어",
    "toeic", "toefl", "teps", "opic", "jlpt", "hsk",
    # 비기술
    "운전면허", "컴퓨터활용능력", "워드",
    "한글", "한셀", "한쇼",
    "powerpoint", "excel", "microsoft office",
})


def _is_non_tech_skill(name: str) -> bool:
    """자격증·어학·비기술 항목이면 True."""
    cleaned = name.strip()
    if _CERT_PATTERN.search(cleaned):
        return True
    return cleaned.lower() in _NON_TECH_NAMES
