"""Setup-token usage via `anthropic-ratelimit-unified-*` headers (usage endpoint 403s)."""

import json
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from claude_swap import oauth


PROBE_HEADERS = {
    "anthropic-ratelimit-unified-5h-utilization": "0.25",
    "anthropic-ratelimit-unified-5h-reset": "1791536400",
    "anthropic-ratelimit-unified-7d-utilization": "0.89",
    "anthropic-ratelimit-unified-7d-reset": "1791864000",
}


def _hdrs(d: dict) -> Message:
    msg = Message()
    for k, v in d.items():
        msg[k] = v
    return msg


def _resp(headers: Message, body: bytes = b"{}"):
    resp = MagicMock()
    resp.headers = headers
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


@pytest.fixture(autouse=True)
def _clear_probe_memo():
    oauth._header_probe_tokens.clear()
    yield
    oauth._header_probe_tokens.clear()


def test_headers_convert_fraction_to_percent_and_epoch_to_iso():
    data = oauth.usage_from_ratelimit_headers(_hdrs(PROBE_HEADERS))
    assert data["five_hour"]["utilization"] == 25.0
    assert data["seven_day"]["utilization"] == 89.0
    assert data["seven_day"]["resets_at"].startswith("2026-")
    result = oauth.build_usage_result(data)
    assert result["five_hour"]["pct"] == 25.0
    assert oauth.account_headroom(result) == pytest.approx(11.0)


def test_no_window_headers_yields_none():
    assert oauth.usage_from_ratelimit_headers(_hdrs({"x-other": "1"})) is None
    assert oauth.usage_from_ratelimit_headers(None) is None


def test_403_falls_back_to_probe_and_memoizes_token():
    forbidden = urllib.error.HTTPError(
        "https://api.anthropic.com/api/oauth/usage", 403, "Forbidden", hdrs=None, fp=None
    )
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if req.full_url.endswith("/api/oauth/usage"):
            raise forbidden
        assert req.get_method() == "POST"
        assert json.loads(req.data)["max_tokens"] == 1
        return _resp(_hdrs(PROBE_HEADERS))

    with patch("claude_swap.oauth.urllib.request.urlopen", side_effect=fake_urlopen):
        first = oauth.request_usage_data("sk-ant-oat01-setup")
        second = oauth.request_usage_data("sk-ant-oat01-setup")

    assert first["seven_day"]["utilization"] == 89.0
    assert second == first
    # 403 learned once; the second poll skips the usage endpoint entirely.
    assert calls == [
        "https://api.anthropic.com/api/oauth/usage",
        oauth.HEADER_PROBE_URL,
        oauth.HEADER_PROBE_URL,
    ]


def test_exhausted_account_429_still_reports_usage():
    exhausted = dict(PROBE_HEADERS)
    exhausted["anthropic-ratelimit-unified-5h-utilization"] = "1.0"
    err = urllib.error.HTTPError(
        oauth.HEADER_PROBE_URL, 429, "Too Many Requests", hdrs=_hdrs(exhausted), fp=None
    )
    with patch("claude_swap.oauth.urllib.request.urlopen", side_effect=err):
        data = oauth.request_usage_via_headers("tok")
    assert data["five_hour"]["utilization"] == 100.0


def test_probe_error_without_headers_reraises_for_normal_backoff():
    err = urllib.error.HTTPError(
        oauth.HEADER_PROBE_URL, 429, "Too Many Requests", hdrs=_hdrs({"retry-after": "30"}), fp=None
    )
    with patch("claude_swap.oauth.urllib.request.urlopen", side_effect=err):
        with pytest.raises(urllib.error.HTTPError):
            oauth.request_usage_via_headers("tok")


def test_non_403_usage_errors_are_untouched():
    err = urllib.error.HTTPError(
        "https://api.anthropic.com/api/oauth/usage", 401, "Unauthorized", hdrs=None, fp=None
    )
    with patch("claude_swap.oauth.urllib.request.urlopen", side_effect=err) as op:
        with pytest.raises(urllib.error.HTTPError):
            oauth.request_usage_data("tok")
    assert op.call_count == 1  # no probe on 401 — that path belongs to refresh


SETUP_CREDS = json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-setup", "scopes": ["user:inference"]}})
OAUTH_CREDS = json.dumps({"claudeAiOauth": {
    "accessToken": "at", "refreshToken": "rt", "expiresAt": 9_999_999_999_999,
    "scopes": ["user:inference", "user:profile"],
}})


def test_is_setup_token_detection():
    assert oauth.is_setup_token(json.loads(SETUP_CREDS)["claudeAiOauth"])
    assert not oauth.is_setup_token(json.loads(OAUTH_CREDS)["claudeAiOauth"])
    assert not oauth.is_setup_token(None)


def test_setup_token_account_never_touches_usage_endpoint():
    urls = []

    def fake_urlopen(req, timeout=0):
        urls.append(req.full_url)
        return _resp(_hdrs(PROBE_HEADERS))

    with patch("claude_swap.oauth.urllib.request.urlopen", side_effect=fake_urlopen):
        out = oauth.try_fetch_usage_for_account("10", "t@x.y", SETUP_CREDS, is_active=False)
    assert out.error is None
    assert out.usage["seven_day"]["pct"] == 89.0
    assert urls == [oauth.HEADER_PROBE_URL]
