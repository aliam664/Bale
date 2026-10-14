"""کلاینت سبک و async برای API بازوی بله.

همهٔ درخواست‌ها به شکل ``POST https://tapi.bale.ai/bot<TOKEN>/<METHOD>`` با بدنهٔ JSON ارسال می‌شوند
(طبق مستندات، application/json برای همهٔ متدها به‌جز آپلود فایل پشتیبانی می‌شود).

پاسخ همیشه ``{"ok": bool, "result": ..., "description": ..., "error_code": ..., "parameters": {"retry_after": n}}`` است.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)


class BaleAPIError(Exception):
    """خطای منطقی API (ok=false) یا خطای شبکه پس از تلاش‌های مجدد."""

    def __init__(self, method: str, error_code: Optional[int], description: str,
                 retry_after: Optional[int] = None):
        super().__init__(f"{method} failed: [{error_code}] {description}")
        self.method = method
        self.error_code = error_code
        self.description = description
        self.retry_after = retry_after


class BaleAPI:
    """پوشش نازک روی متدهای HTTP بله. فقط متدهایی که ربات بازی نیاز دارد پیاده شده‌اند؛
    هر متد دیگری را می‌توان با ``request("methodName", **params)`` صدا زد."""

    def __init__(self, token: str, base_url: str = "https://tapi.bale.ai",
                 poll_timeout: int = 30, max_retries: int = 3,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self._base = f"{base_url.rstrip('/')}/bot{token}"
        self._file_base = f"{base_url.rstrip('/')}/file/bot{token}"
        self._poll_timeout = poll_timeout
        self._max_retries = max_retries
        # تایم‌اوت خواندن باید از timeout لانگ‌پولینگ بیشتر باشد. (transport فقط برای تست)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=poll_timeout + 15),
                                         transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ core
    async def request(self, method: str, **params: Any) -> Any:
        payload = {k: v for k, v in params.items() if v is not None}
        url = f"{self._base}/{method}"
        last_error: Optional[BaseException] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = await self._client.post(url, json=payload)
            except httpx.HTTPError as exc:  # خطای شبکه/تایم‌اوت
                last_error = exc
                log.warning("network error on %s (attempt %d/%d): %s", method, attempt, self._max_retries, exc)
                await asyncio.sleep(min(2 * attempt, 10))
                continue

            try:
                data = resp.json()
            except ValueError:
                raise BaleAPIError(method, resp.status_code, f"non-JSON response: {resp.text[:200]!r}")

            if data.get("ok"):
                return data.get("result")

            retry_after = (data.get("parameters") or {}).get("retry_after")
            if retry_after is None and resp.status_code == 429:
                retry_after = 3
            if retry_after and attempt < self._max_retries:
                log.warning("rate limited on %s; sleeping %ss", method, retry_after)
                await asyncio.sleep(float(retry_after) + 0.5)
                continue

            raise BaleAPIError(method, data.get("error_code", resp.status_code),
                               str(data.get("description", data)), retry_after)

        raise BaleAPIError(method, None, f"network error after {self._max_retries} attempts: {last_error}")

    # --------------------------------------------------------------- helpers
    async def get_me(self) -> Dict[str, Any]:
        return await self.request("getMe")

    async def delete_webhook(self) -> Any:
        return await self.request("deleteWebhook")

    async def get_updates(self, offset: Optional[int] = None, limit: int = 100,
                          timeout: Optional[int] = None) -> List[Dict[str, Any]]:
        result = await self.request(
            "getUpdates", offset=offset, limit=limit,
            timeout=self._poll_timeout if timeout is None else timeout,
        )
        return result or []

    async def send_message(self, chat_id: int, text: str, reply_markup: Optional[dict] = None,
                           reply_to_message_id: Optional[int] = None) -> Dict[str, Any]:
        return await self.request("sendMessage", chat_id=chat_id, text=text,
                                  reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)

    async def edit_message_text(self, chat_id: int, message_id: int, text: str,
                                reply_markup: Optional[dict] = None) -> Any:
        return await self.request("editMessageText", chat_id=chat_id, message_id=message_id,
                                  text=text, reply_markup=reply_markup)

    async def edit_message_reply_markup(self, chat_id: int, message_id: int,
                                        reply_markup: Optional[dict] = None) -> Any:
        return await self.request("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                                  reply_markup=reply_markup)

    async def delete_message(self, chat_id: int, message_id: int) -> Any:
        return await self.request("deleteMessage", chat_id=chat_id, message_id=message_id)

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None,
                                    show_alert: Optional[bool] = None) -> Any:
        return await self.request("answerCallbackQuery", callback_query_id=callback_query_id,
                                  text=text, show_alert=show_alert)

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> Any:
        return await self.request("sendChatAction", chat_id=chat_id, action=action)

    def file_url(self, file_path: str) -> str:
        return f"{self._file_base}/{file_path}"
