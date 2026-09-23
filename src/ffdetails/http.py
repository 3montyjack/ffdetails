"""HTTP transport used to read source payloads."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ffdetails.errors import FetchError

USER_AGENT = "ffdetails/0.1 (+https://github.com/3montyjack/ffdetails)"


class UrllibClient:
    """GET JSON or text with the stdlib HTTP client."""

    def __init__(self, timeout: float = 60, user_agent: str = USER_AGENT) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def get_json(self, url: str) -> Any:
        body = self._get(url)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchError(f"response was not JSON: {url}") from exc

    def get_text(self, url: str) -> str:
        body = self._get(url)
        return body.decode("utf-8", errors="replace")

    def _get(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as exc:
            raise FetchError(f"HTTP {exc.code} for {url}") from exc
        except URLError as exc:
            raise FetchError(f"request failed for {url}: {exc.reason}") from exc
