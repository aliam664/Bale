"""API جعلی بله برای تست‌ها: همان متدهای BaleAPI را دارد ولی فقط فراخوانی‌ها را ثبت می‌کند."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bot.bale_api import BaleAPIError


class FakeAPI:
    def __init__(self, fail_edit_ids: Tuple[int, ...] = ()) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.next_message_id = 100
        self.messages: Dict[Tuple[int, int], Dict[str, Any]] = {}     # (chat_id, message_id) -> محتوا
        self.sent_ids: Dict[int, List[int]] = {}                       # chat_id -> شناسه‌های ارسالی به ترتیب
        self.fail_edit_ids = set(fail_edit_ids)
        self.closed = False

    # ------------------------------------------------------------ API methods
    async def get_me(self) -> Dict[str, Any]:
        self.calls.append(("getMe", {}))
        return {"id": 1, "is_bot": True, "first_name": "Dooz", "username": "doozbot"}

    async def delete_webhook(self) -> Any:
        self.calls.append(("deleteWebhook", {}))
        return True

    async def get_updates(self, offset: Optional[int] = None, limit: int = 100,
                          timeout: Optional[int] = None) -> List[Dict[str, Any]]:
        self.calls.append(("getUpdates", {"offset": offset}))
        return []

    async def send_message(self, chat_id: int, text: str, reply_markup: Optional[dict] = None,
                           reply_to_message_id: Optional[int] = None) -> Dict[str, Any]:
        self.calls.append(("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}))
        mid = self.next_message_id
        self.next_message_id += 1
        self.messages[(chat_id, mid)] = {"text": text, "reply_markup": reply_markup}
        self.sent_ids.setdefault(chat_id, []).append(mid)
        return {"message_id": mid, "chat": {"id": chat_id, "type": "private"}, "text": text}

    async def edit_message_text(self, chat_id: int, message_id: int, text: str,
                                reply_markup: Optional[dict] = None) -> Any:
        self.calls.append(("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                               "text": text, "reply_markup": reply_markup}))
        if message_id in self.fail_edit_ids or (chat_id, message_id) not in self.messages:
            raise BaleAPIError("editMessageText", 400, "Bad Request: message to edit not found")
        self.messages[(chat_id, message_id)] = {"text": text, "reply_markup": reply_markup}
        return True

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None,
                                    show_alert: Optional[bool] = None) -> Any:
        self.calls.append(("answerCallbackQuery", {"callback_query_id": callback_query_id,
                                                   "text": text, "show_alert": show_alert}))
        return True

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> Any:
        self.calls.append(("sendChatAction", {"chat_id": chat_id, "action": action}))
        return True

    async def close(self) -> None:
        self.closed = True

    # --------------------------------------------------------------- helpers
    def calls_of(self, method: str) -> List[Dict[str, Any]]:
        return [p for m, p in self.calls if m == method]

    def last_sent_id(self, chat_id: int) -> int:
        return self.sent_ids[chat_id][-1]

    def content(self, chat_id: int, message_id: int) -> Dict[str, Any]:
        return self.messages[(chat_id, message_id)]

    def last_answer(self) -> Dict[str, Any]:
        return self.calls_of("answerCallbackQuery")[-1]

    def clear(self) -> None:
        self.calls.clear()


def callback_datas(markup: Optional[dict]) -> List[str]:
    """لیست مسطح callback_data های یک InlineKeyboardMarkup."""
    if not markup:
        return []
    return [btn["callback_data"] for row in markup["inline_keyboard"] for btn in row]


def button_texts(markup: Optional[dict]) -> List[List[str]]:
    if not markup:
        return []
    return [[btn["text"] for btn in row] for row in markup["inline_keyboard"]]
