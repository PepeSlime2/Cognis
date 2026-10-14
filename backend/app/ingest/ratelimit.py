from __future__ import annotations

import datetime as dt
import random
import time
from collections.abc import Callable
from typing import Any

import requests

GITHUB_RATE_LIMIT_URL = "https://api.github.com/rate_limit"
DEFAULT_TIMEOUT = 30
MIN_REMAINING_THRESHOLD = 200
MAX_PAUSE_WAIT_SECONDS = 300  # 5 minutos


class RateLimitPaused(Exception):
    def __init__(self, reset_at: dt.datetime, remaining: int, message: str | None = None) -> None:
        self.reset_at = reset_at
        self.remaining = remaining
        msg = message or f"Rate limit do GitHub atingiu limite de segurança ({remaining} restantes). Pausado até {reset_at.isoformat()}."
        super().__init__(msg)


def check_github_rate_limit(
    token: str,
    now: dt.datetime | None = None,
    min_remaining: int = MIN_REMAINING_THRESHOLD,
    max_wait_seconds: int = MAX_PAUSE_WAIT_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(
            GITHUB_RATE_LIMIT_URL,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "skipped", "error": str(exc)}

    resources = payload.get("resources", {})
    core = resources.get("core", {})
    remaining = core.get("remaining")
    reset_timestamp = core.get("reset")

    if remaining is None or reset_timestamp is None:
        return {"status": "ok", "remaining": None, "reset_at": None}

    current_time = now or dt.datetime.now(dt.timezone.utc)
    reset_at = dt.datetime.fromtimestamp(reset_timestamp, tz=dt.timezone.utc)

    if remaining < min_remaining:
        wait_seconds = (reset_at - current_time).total_seconds()
        if 0 < wait_seconds <= max_wait_seconds:
            sleeper(wait_seconds)
            return {"status": "waited", "remaining": remaining, "reset_at": reset_at, "waited_seconds": wait_seconds}
        raise RateLimitPaused(reset_at=reset_at, remaining=remaining)

    return {"status": "ok", "remaining": remaining, "reset_at": reset_at}


def request_with_retry(
    method: str,
    url: str,
    max_retries: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    last_response: requests.Response | None = None

    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, **kwargs)
            last_response = response

            # Rate limit 403/429
            if response.status_code in (403, 429):
                retry_after_hdr = response.headers.get("Retry-After")
                remaining_hdr = response.headers.get("X-RateLimit-Remaining")
                reset_hdr = response.headers.get("X-RateLimit-Reset")

                is_rate_limited = (remaining_hdr == "0") or (retry_after_hdr is not None) or (response.status_code == 429)
                if is_rate_limited:
                    wait_seconds: float = 0
                    if retry_after_hdr:
                        try:
                            wait_seconds = float(retry_after_hdr)
                        except ValueError:
                            wait_seconds = 60
                    elif reset_hdr:
                        try:
                            reset_ts = float(reset_hdr)
                            now_ts = time.time()
                            wait_seconds = max(0, reset_ts - now_ts)
                        except ValueError:
                            wait_seconds = 60

                    if wait_seconds > MAX_PAUSE_WAIT_SECONDS:
                        reset_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=wait_seconds)
                        raise RateLimitPaused(reset_at=reset_at, remaining=0)

                    if attempt < max_retries - 1:
                        backoff = max(wait_seconds, (2 ** attempt) + random.uniform(0.1, 0.5))
                        sleeper(backoff)
                        continue

            # Erros 5xx
            if 500 <= response.status_code < 600:
                if attempt < max_retries - 1:
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.5)
                    sleeper(backoff)
                    continue

            return response
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt < max_retries - 1:
                backoff = (2 ** attempt) + random.uniform(0.1, 0.5)
                sleeper(backoff)
                continue
            raise exc

    if last_response is not None:
        return last_response
    raise RuntimeError("Falha ao executar requisição com repetição.")
