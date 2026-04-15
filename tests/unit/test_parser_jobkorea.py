"""parser.jobkorea 단위 테스트 — tech_stack 필터링 및 raw_text 노이즈 제거."""
from parser.jobkorea import (
    _extract_tech_stack,
    _is_non_tech_skill,
    _remove_noise_sections,
    parse_job_iframe,
)


class TestIsNonTechSkill:
    """자격증·어학·비기술 항목 판별."""

    def test_certification_patterns(self):
        assert _is_non_tech_skill("정보처리기사 자격")
        assert _is_non_tech_skill("정보처리기능사 자격")
        assert _is_non_tech_skill("공조냉동기계기사 자격")
        assert _is_non_tech_skill("토목기사 자격")
        assert _is_non_tech_skill("정보통신산업기사 자격")

    def test_language_skills(self):
        assert _is_non_tech_skill("영어")
        assert _is_non_tech_skill("비즈니스영어")
        assert _is_non_tech_skill("일본어")
        assert _is_non_tech_skill("TOEIC")
        assert _is_non_tech_skill("toeic")
        assert _is_non_tech_skill("JLPT")

    def test_non_tech_items(self):
        assert _is_non_tech_skill("운전면허")
        assert _is_non_tech_skill("컴퓨터활용능력")
        assert _is_non_tech_skill("워드")
        assert _is_non_tech_skill("Excel")
        assert _is_non_tech_skill("PowerPoint")
        assert _is_non_tech_skill("Microsoft Office")

    def test_real_tech_not_filtered(self):
        assert not _is_non_tech_skill("Python")
        assert not _is_non_tech_skill("JAVA")
        assert not _is_non_tech_skill("Docker")
        assert not _is_non_tech_skill("kubernetes")
        assert not _is_non_tech_skill("React")
        assert not _is_non_tech_skill("Spring Boot")
        assert not _is_non_tech_skill("PostgreSQL")
        assert not _is_non_tech_skill("Linux")


class TestExtractTechStack:
    """_extract_tech_stack 에서 비기술 항목이 제외되는지 검증."""

    @staticmethod
    def _make_skill_html(name: str) -> str:
        return (
            f'\\"name\\":\\"{name}\\"'
            f',\\"rank\\":0'
            f',\\"manualInput\\":false'
            f',\\"skillTypeCode\\":\\"HARD_SKILL\\"'
        )

    def test_filters_certification(self):
        html = self._make_skill_html("정보처리기사 자격")
        result = _extract_tech_stack(html)
        assert result == []

    def test_filters_language(self):
        html = self._make_skill_html("TOEIC")
        result = _extract_tech_stack(html)
        assert result == []

    def test_keeps_real_tech(self):
        html = self._make_skill_html("Python")
        result = _extract_tech_stack(html)
        assert result == ["Python"]

    def test_mixed_skills(self):
        skills = ["JAVA", "영어", "Docker", "정보처리기사 자격", "React"]
        html = " ".join(self._make_skill_html(s) for s in skills)
        result = _extract_tech_stack(html)
        assert result == ["Java", "Docker", "React"]


class TestRemoveNoiseSections:
    """복리후생·전형절차 등 노이즈 섹션 제거."""

    def test_removes_benefits_section(self):
        text = (
            "담당업무\n"
            "백엔드 서버 개발\n"
            "자격요건\n"
            "Python 3년 이상\n"
            "복리후생\n"
            "4대 보험\n"
            "명절선물\n"
        )
        result = _remove_noise_sections(text)
        assert "백엔드 서버 개발" in result
        assert "Python 3년 이상" in result
        assert "복리후생" not in result
        assert "4대 보험" not in result

    def test_removes_process_section(self):
        text = (
            "담당업무\n"
            "서비스 개발\n"
            "전형절차\n"
            "서류전형\n"
            "면접\n"
        )
        result = _remove_noise_sections(text)
        assert "서비스 개발" in result
        assert "전형절차" not in result
        assert "서류전형" not in result

    def test_removes_application_info(self):
        text = (
            "우대사항\n"
            "AWS 경험\n"
            "접수기간 및 방법\n"
            "채용 시 마감\n"
        )
        result = _remove_noise_sections(text)
        assert "AWS 경험" in result
        assert "접수기간" not in result

    def test_no_noise_returns_original(self):
        text = "담당업무\n서비스 개발\n자격요건\nPython"
        result = _remove_noise_sections(text)
        assert result == text

    def test_empty_after_noise_removal(self):
        text = "복리후생\n4대 보험"
        result = _remove_noise_sections(text)
        assert result == ""

    def test_first_noise_header_wins(self):
        text = (
            "담당업무\n"
            "개발\n"
            "복리후생\n"
            "보험\n"
            "전형절차\n"
            "면접\n"
        )
        result = _remove_noise_sections(text)
        assert "개발" in result
        assert "복리후생" not in result
        assert "전형절차" not in result

    def test_removes_top_noise_before_jd_start(self):
        text = (
            "기업 개요\n"
            "업력 9년차\n"
            "대기업\n"
            "모집분야\n"
            "백엔드 개발자\n"
            "자격요건\n"
            "Python 3년\n"
        )
        result = _remove_noise_sections(text)
        assert "기업 개요" not in result
        assert "업력 9년차" not in result
        assert "모집분야" in result
        assert "Python 3년" in result

    def test_removes_both_top_and_bottom_noise(self):
        text = (
            "회사명\n"
            "설립일 2015년\n"
            "담당업무\n"
            "서버 개발\n"
            "자격요건\n"
            "Java 경험\n"
            "복리후생\n"
            "4대 보험\n"
            "전형절차\n"
            "면접\n"
        )
        result = _remove_noise_sections(text)
        assert "회사명" not in result
        assert "설립일" not in result
        assert "담당업무" in result
        assert "서버 개발" in result
        assert "Java 경험" in result
        assert "복리후생" not in result

    def test_no_jd_marker_keeps_from_beginning(self):
        text = (
            "백엔드 개발자 모집\n"
            "Python 경험 필수\n"
            "복리후생\n"
            "4대 보험\n"
        )
        result = _remove_noise_sections(text)
        assert "백엔드 개발자 모집" in result
        assert "Python 경험 필수" in result
        assert "복리후생" not in result


class TestParseJobIframe:
    """parse_job_iframe 통합 검증."""

    def test_noise_removed_from_output(self):
        html = (
            "<html><body>"
            "<p>담당업무</p><p>백엔드 개발</p>"
            "<p>자격요건</p><p>Python 경험</p>"
            "<p>복리후생</p><p>4대 보험</p><p>점심 제공</p>"
            "</body></html>"
        )
        result = parse_job_iframe(html)
        assert result is not None
        assert "백엔드 개발" in result
        assert "복리후생" not in result
        assert "4대 보험" not in result

    def test_image_jd_returns_none(self):
        html = '<html><body><img src="jd.png"><p>짧음</p></body></html>'
        result = parse_job_iframe(html)
        assert result is None

    def test_empty_text_returns_none(self):
        html = "<html><body></body></html>"
        result = parse_job_iframe(html)
        assert result is None
