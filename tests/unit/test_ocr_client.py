"""ocr_client 단위 테스트. Cloud Vision API 호출은 mock 으로 대체한다."""
from unittest.mock import MagicMock, patch

import pytest

import ocr_client


@pytest.fixture(autouse=True)
def _reset_credentials():
    """각 테스트 전에 인증 정보 상태를 초기화."""
    ocr_client._credentials = None
    yield
    ocr_client._credentials = None


def _mock_vision_response(*texts):
    """Cloud Vision API 응답을 모사하는 Response 객체를 생성한다."""
    responses = []
    for text in texts:
        if text:
            responses.append({"fullTextAnnotation": {"text": text}})
        else:
            responses.append({})

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"responses": responses}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


@patch("ocr_client._get_credentials")
@patch("ocr_client.requests.post")
def test_single_image_returns_text(mock_post, mock_creds):
    """이미지 1장 전송 시 OCR 결과 텍스트를 반환한다."""
    mock_creds.return_value = MagicMock(token="fake-token")
    mock_post.return_value = _mock_vision_response("주요업무\n백엔드 개발")

    result = ocr_client.call_ocr(["base64data"])

    assert result == "주요업무\n백엔드 개발"
    mock_post.assert_called_once()


@patch("ocr_client._get_credentials")
@patch("ocr_client.requests.post")
def test_multiple_images_concatenated(mock_post, mock_creds):
    """여러 이미지의 OCR 결과가 줄바꿈으로 합산된다."""
    mock_creds.return_value = MagicMock(token="fake-token")
    mock_post.return_value = _mock_vision_response("모집분야", "자격요건")

    result = ocr_client.call_ocr(["img1", "img2"])

    assert result == "모집분야\n자격요건"


@patch("ocr_client._get_credentials")
@patch("ocr_client.requests.post")
def test_empty_ocr_result_skipped(mock_post, mock_creds):
    """OCR 결과가 없으면 합산에서 제외된다."""
    mock_creds.return_value = MagicMock(token="fake-token")
    mock_post.return_value = _mock_vision_response("", "자격요건")

    result = ocr_client.call_ocr(["img1", "img2"])

    assert result == "자격요건"


@patch("ocr_client._get_credentials")
@patch("ocr_client.requests.post")
def test_all_empty_returns_empty_string(mock_post, mock_creds):
    """모든 OCR 결과가 비면 빈 문자열을 반환한다."""
    mock_creds.return_value = MagicMock(token="fake-token")
    mock_post.return_value = _mock_vision_response("")

    result = ocr_client.call_ocr(["img1"])

    assert result == ""


@patch("ocr_client._get_credentials")
@patch("ocr_client.requests.post")
def test_request_includes_language_hint(mock_post, mock_creds):
    """요청에 한국어 languageHints 가 포함된다."""
    mock_creds.return_value = MagicMock(token="fake-token")
    mock_post.return_value = _mock_vision_response("텍스트")

    ocr_client.call_ocr(["img1"])

    call_kwargs = mock_post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    image_req = body["requests"][0]
    assert image_req["imageContext"]["languageHints"] == ["ko"]


@patch("ocr_client._get_credentials")
@patch("ocr_client.requests.post")
def test_request_uses_bearer_token(mock_post, mock_creds):
    """요청 헤더에 Bearer 토큰이 포함된다."""
    mock_creds.return_value = MagicMock(token="test-token-123")
    mock_post.return_value = _mock_vision_response("텍스트")

    ocr_client.call_ocr(["img1"])

    call_kwargs = mock_post.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
    assert headers["Authorization"] == "Bearer test-token-123"


@patch("ocr_client._get_credentials")
@patch("ocr_client.requests.post")
def test_batch_request_sends_all_images(mock_post, mock_creds):
    """여러 이미지를 한 번의 API 호출로 배치 전송한다."""
    mock_creds.return_value = MagicMock(token="fake-token")
    mock_post.return_value = _mock_vision_response("a", "b", "c")

    ocr_client.call_ocr(["img1", "img2", "img3"])

    call_kwargs = mock_post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert len(body["requests"]) == 3
    mock_post.assert_called_once()
