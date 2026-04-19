"""ocr_client 단위 테스트. ONNX OCR 엔진은 mock 으로 대체한다."""
from unittest.mock import MagicMock, patch

import pytest

import ocr_client


@pytest.fixture(autouse=True)
def _reset_ocr_engine():
    """각 테스트 전에 OCR 엔진 상태를 초기화."""
    ocr_client._ocr_engine = None
    yield
    ocr_client._ocr_engine = None


@patch("ocr_client._preprocess_image")
@patch("ocr_client._load_ocr")
def test_single_image_returns_text(mock_load, mock_preprocess):
    """이미지 1장 전송 시 OCR 결과 텍스트를 반환한다."""
    mock_preprocess.return_value = "fake_np_array"
    mock_engine = MagicMock()
    mock_engine.return_value = (
        [([0, 0, 100, 30], "주요업무", 0.95), ([0, 30, 100, 60], "백엔드 개발", 0.90)],
        {"det": 0.1, "rec": 0.2},
    )
    ocr_client._ocr_engine = mock_engine

    result = ocr_client.call_ocr(["base64data"])

    assert result == "주요업무\n백엔드 개발"
    mock_engine.assert_called_once_with("fake_np_array")


@patch("ocr_client._preprocess_image")
@patch("ocr_client._load_ocr")
def test_multiple_images_concatenated(mock_load, mock_preprocess):
    """여러 이미지의 OCR 결과가 줄바꿈으로 합산된다."""
    mock_preprocess.return_value = "fake_np_array"
    mock_engine = MagicMock()
    mock_engine.side_effect = [
        ([([0, 0, 1, 1], "모집분야", 0.9)], {"det": 0.1}),
        ([([0, 0, 1, 1], "자격요건", 0.9)], {"det": 0.1}),
    ]
    ocr_client._ocr_engine = mock_engine

    result = ocr_client.call_ocr(["img1", "img2"])

    assert result == "모집분야\n자격요건"
    assert mock_engine.call_count == 2


@patch("ocr_client._preprocess_image")
@patch("ocr_client._load_ocr")
def test_empty_ocr_result_skipped(mock_load, mock_preprocess):
    """OCR 결과가 없으면(None) 합산에서 제외된다."""
    mock_preprocess.return_value = "fake_np_array"
    mock_engine = MagicMock()
    mock_engine.side_effect = [
        (None, {"det": 0.1}),
        ([([0, 0, 1, 1], "자격요건", 0.9)], {"det": 0.1}),
    ]
    ocr_client._ocr_engine = mock_engine

    result = ocr_client.call_ocr(["img1", "img2"])

    assert result == "자격요건"


@patch("ocr_client._preprocess_image")
@patch("ocr_client._load_ocr")
def test_all_empty_returns_empty_string(mock_load, mock_preprocess):
    """모든 OCR 결과가 비면 빈 문자열을 반환한다."""
    mock_preprocess.return_value = "fake_np_array"
    mock_engine = MagicMock()
    mock_engine.return_value = (None, {"det": 0.1})
    ocr_client._ocr_engine = mock_engine

    result = ocr_client.call_ocr(["img1"])

    assert result == ""


@patch("ocr_client._load_ocr")
def test_preprocess_resizes_large_image(mock_load):
    """1500px 초과 이미지가 비율 유지하며 리사이즈된다."""
    import base64
    from PIL import Image
    import io

    img = Image.new("RGB", (3000, 2000), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    result = ocr_client._preprocess_image(img_b64)

    assert max(result.shape[0], result.shape[1]) <= 1500


@patch("ocr_client._load_ocr")
def test_preprocess_keeps_small_image(mock_load):
    """1500px 이하 이미지는 리사이즈하지 않는다."""
    import base64
    from PIL import Image
    import io

    img = Image.new("RGB", (800, 600), color=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    result = ocr_client._preprocess_image(img_b64)

    assert result.shape[1] == 800
    assert result.shape[0] == 600


@patch("ocr_client._preprocess_image")
@patch("ocr_client._load_ocr")
def test_lazy_loading_called(mock_load, mock_preprocess):
    """call_ocr 호출 시 _load_ocr 가 한 번 호출된다."""
    mock_preprocess.return_value = "fake_np_array"
    mock_engine = MagicMock()
    mock_engine.return_value = (None, {})
    ocr_client._ocr_engine = mock_engine

    ocr_client.call_ocr(["img1"])

    mock_load.assert_called_once()
