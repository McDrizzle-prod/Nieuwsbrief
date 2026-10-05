import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, ROOT)

from scraper.util import FetchError  # noqa: E402


class FakeResponse:
    def __init__(self, url: str, content: bytes):
        self.url = url
        self.content = content
        self.status_code = 200
        self.text = content.decode("utf-8")

    def json(self):
        return json.loads(self.content)


class FakeHttp:
    """Vervangt Http: geeft per URL de inhoud van een fixture-bestand terug."""

    def __init__(self, routes: dict[str, str]):
        self.routes = dict(routes)
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params))
        name = self.routes.get(url)
        if name is None:
            raise FetchError(f"HTTP 404 bij {url}")
        with open(os.path.join(FIXTURES, name), "rb") as fh:
            return FakeResponse(url, fh.read())


@pytest.fixture
def fake_http():
    return FakeHttp
