"""ocr_client 단위 테스트. 외부 HTTP 호출은 mock 으로 대체한다."""
import json
from unittest.mock import MagicMock, patch

import pytest

from ocr_client import call_ocr


@patch("ocr_client.requests.post")
def test_single_image_returns_text(mock_post):
    """이미지 1장 전송 시 OCR 결과 텍스트를 반환한다."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "주요업무\n백엔드 개발"}
    mock_post.return_value = mock_resp

    result = call_ocr(["base64data"], "http://ocr:8500")

    assert result == "주요업무\n백엔드 개발"
    mock_post.assert_called_once_with(
        "http://ocr:8500/ocr",
        json={"image_b64": "base64data"},
        headers={},
        timeout=30,
    )


@patch("ocr_client.requests.post")
def test_multiple_images_concatenated(mock_post):
    """여러 이미지의 OCR 결과가 줄바꿈으로 합산된다."""
    resp1 = MagicMock()
    resp1.json.return_value = {"text": "모집분야"}
    resp2 = MagicMock()
    resp2.json.return_value = {"text": "자격요건"}
    mock_post.side_effect = [resp1, resp2]

    result = call_ocr(["img1", "img2"], "http://ocr:8500")

    assert result == "모집분야\n자격요건"
    assert mock_post.call_count == 2


@patch("ocr_client.requests.post")
def test_empty_ocr_result_skipped(mock_post):
    """OCR 결과가 빈 문자열이면 합산에서 제외된다."""
    resp1 = MagicMock()
    resp1.json.return_value = {"text": ""}
    resp2 = MagicMock()
    resp2.json.return_value = {"text": "자격요건"}
    mock_post.side_effect = [resp1, resp2]

    result = call_ocr(["img1", "img2"], "http://ocr:8500")

    assert result == "자격요건"


@patch("ocr_client.requests.post")
def test_all_empty_returns_empty_string(mock_post):
    """모든 OCR 결과가 비면 빈 문자열을 반환한다."""
    resp = MagicMock()
    resp.json.return_value = {"text": ""}
    mock_post.return_value = resp

    result = call_ocr(["img1"], "http://ocr:8500")

    assert result == ""


@patch("ocr_client.requests.post")
def test_server_error_propagates(mock_post):
    """OCR 서버 오류 시 예외가 전파된다."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("500 Server Error")
    mock_post.return_value = mock_resp

    with pytest.raises(Exception, match="500 Server Error"):
        call_ocr(["img1"], "http://ocr:8500")


@patch("ocr_client.requests.post")
def test_trailing_slash_handled(mock_post):
    """server_url 끝에 슬래시가 있어도 정상 동작한다."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "결과"}
    mock_post.return_value = mock_resp

    call_ocr(["img1"], "http://ocr:8500/")

    mock_post.assert_called_once_with(
        "http://ocr:8500/ocr",
        json={"image_b64": "img1"},
        headers={},
        timeout=30,
    )


@patch("ocr_client.requests.post")
def test_api_key_sent_in_header(mock_post):
    """api_key 가 설정되면 X-API-Key 헤더에 포함된다."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "결과"}
    mock_post.return_value = mock_resp

    call_ocr(["img1"], "http://ocr:8500", api_key="secret-123")

    mock_post.assert_called_once_with(
        "http://ocr:8500/ocr",
        json={"image_b64": "img1"},
        headers={"X-API-Key": "secret-123"},
        timeout=30,
    )


@patch("ocr_client.requests.post")
def test_no_api_key_sends_no_header(mock_post):
    """api_key 가 빈 문자열이면 X-API-Key 헤더를 보내지 않는다."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "결과"}
    mock_post.return_value = mock_resp

    call_ocr(["img1"], "http://ocr:8500", api_key="")

    mock_post.assert_called_once_with(
        "http://ocr:8500/ocr",
        json={"image_b64": "img1"},
        headers={},
        timeout=30,
    )
