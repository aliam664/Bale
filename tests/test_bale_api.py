"""تست کلاینت HTTP با httpx.MockTransport: قالب درخواست، retry_after، خطاها."""
from __future__ import annotations

import json
from typing import List

import httpx
import pytest

from bot.bale_api import BaleAPI, BaleAPIError


def make_api(handler, **kw) -> BaleAPI:
    return BaleAPI("123:ABC", "https://tapi.bale.ai", poll_timeout=5,
                   transport=httpx.MockTransport(handler), **kw)


@pytest.mark.asyncio
async def test_request_format_and_result():
    seen: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    api = make_api(handler)
    res = await api.send_message(42, "سلام", reply_markup={"inline_keyboard": [[{"text": "a", "callback_data": "x"}]]})
    await api.close()

    assert res == {"message_id": 7}
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "https://tapi.bale.ai/bot123:ABC/sendMessage"
    assert req.headers["content-type"] == "application/json"
    body = json.loads(req.content)
    assert body == {"chat_id": 42, "text": "سلام",
                    "reply_markup": {"inline_keyboard": [[{"text": "a", "callback_data": "x"}]]}}
    assert "reply_to_message_id" not in body      # پارامترهای None حذف می‌شوند


@pytest.mark.asyncio
async def test_get_updates_uses_poll_timeout_and_offset():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": []})

    api = make_api(handler)
    assert await api.get_updates(offset=10) == []
    await api.close()
    assert bodies[0] == {"offset": 10, "limit": 100, "timeout": 5}


@pytest.mark.asyncio
async def test_retry_after_then_success(monkeypatch):
    calls = {"n": 0}
    sleeps: List[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("bot.bale_api.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"ok": False, "error_code": 429, "description": "Too Many Requests",
                                             "parameters": {"retry_after": 2}})
        return httpx.Response(200, json={"ok": True, "result": True})

    api = make_api(handler)
    assert await api.answer_callback_query("abc", text="hi") is True
    await api.close()
    assert calls["n"] == 2 and sleeps == [2.5]


@pytest.mark.asyncio
async def test_api_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})

    api = make_api(handler)
    with pytest.raises(BaleAPIError) as exc:
        await api.send_message(1, "x")
    await api.close()
    assert exc.value.error_code == 400 and "chat not found" in exc.value.description
    assert exc.value.method == "sendMessage"


@pytest.mark.asyncio
async def test_non_json_response_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    api = make_api(handler)
    with pytest.raises(BaleAPIError) as exc:
        await api.get_me()
    await api.close()
    assert exc.value.error_code == 502


@pytest.mark.asyncio
async def test_network_error_retries_then_raises(monkeypatch):
    attempts = {"n": 0}

    async def fake_sleep(s):
        pass

    monkeypatch.setattr("bot.bale_api.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    api = make_api(handler, max_retries=3)
    with pytest.raises(BaleAPIError) as exc:
        await api.get_me()
    await api.close()
    assert attempts["n"] == 3 and exc.value.error_code is None


def test_file_url():
    api = BaleAPI("123:ABC")
    assert api.file_url("photos/a.jpg") == "https://tapi.bale.ai/file/bot123:ABC/photos/a.jpg"
