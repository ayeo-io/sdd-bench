import pytest

from shop import audit, log


@pytest.fixture(autouse=True)
def _clean_records():
    log.clear()
    audit.clear()
    yield
