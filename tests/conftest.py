"""pytest 공통 설정.

- ``src/`` 를 sys.path 최상위에 두어 Lambda 런타임과 동일한 import 경로를 만든다.
- ``app.py`` 가 핸들러 진입 시점에 검증하는 필수 환경변수를 autouse fixture 로 채운다.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
CONSUMER_DIR = PROJECT_ROOT / "consumer"

for d in (SRC_DIR, CONSUMER_DIR):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch):
    """app._required_env 가 던지지 않도록 모든 테스트에 더미 값을 주입."""
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("JOB_DETAIL_QUEUE_URL", "https://sqs.test/detail")
    monkeypatch.setenv("BLOG_EMBEDDING_QUEUE_URL", "https://sqs.test/blog-embedding")
