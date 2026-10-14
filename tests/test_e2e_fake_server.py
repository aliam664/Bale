"""تست سرتاسری: ربات واقعی (BaleAPI روی HTTP) در برابر یک سرور جعلی بله روی localhost.

سناریو: کاربر /start می‌زند → «بازی با کامپیوتر» → سطح «سخت» → تا پایان بازی همیشه اولین خانهٔ خالی را می‌زند.
سرور جعلی با دیدن دکمه‌های هر پیام، کلیک بعدی کاربر را تولید می‌کند.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

import pytest

from bot.app import GameBot
from bot.bale_api import BaleAPI
from bot.config import Settings

TOKEN = "111:FAKE"
USER = 777


class FakeBaleServer:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.updates: List[Dict[str, Any]] = []
        self.update_id = 0
        self.message_id = 0
        self.done = False
        self.log: List[Dict[str, Any]] = []
        self.push_message("/start")

    # ---------------------------------------------------------- scenario
    def push_message(self, text: str) -> None:
        self.update_id += 1
        self.updates.append({"update_id": self.update_id, "message": {
            "message_id": 1, "date": int(time.time()), "text": text,
            "chat": {"id": USER, "type": "private", "first_name": "Tester"},
            "from": {"id": USER, "is_bot": False, "first_name": "Tester"}}})

    def push_click(self, message_id: int, data: str) -> None:
        self.update_id += 1
        self.updates.append({"update_id": self.update_id, "callback_query": {
            "id": f"9{self.update_id}", "data": data,
            "from": {"id": USER, "is_bot": False, "first_name": "Tester"},
            "message": {"message_id": message_id, "date": 0, "chat": {"id": USER, "type": "private"}}}})

    def react(self, message_id: int, text: str, markup: Dict[str, Any] | None) -> None:
        """بر اساس دکمه‌های پیام، کلیک بعدی «کاربر» را تولید می‌کند."""
        if not markup:
            return
        buttons = [b for row in markup["inline_keyboard"] for b in row]
        datas = [b["callback_data"] for b in buttons]
        if "menu:cpu" in datas and not any(d.startswith("cpu:") for d in datas):
            self.push_click(message_id, "menu:cpu")
        elif "cpu:hard" in datas:
            self.push_click(message_id, "cpu:hard")
        elif any(d.startswith("g:again:") for d in datas):
            self.done = True
        elif "نوبت شماست" in text:
            for b in buttons:
                if b["callback_data"].startswith("mv:") and b["text"] == "⬜":
                    self.push_click(message_id, b["callback_data"])
                    break

    # ---------------------------------------------------------- API
    def handle(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            self.log.append({"method": method, **params})
            if method == "getMe":
                return {"ok": True, "result": {"id": 1, "is_bot": True, "first_name": "Fake", "username": "fakebot"}}
            if method == "deleteWebhook":
                return {"ok": True, "result": True}
            if method == "getUpdates":
                batch, self.updates = self.updates, []
                return {"ok": True, "result": batch}
            if method == "sendMessage":
                self.message_id += 1
                mid = self.message_id
                self.react(mid, params["text"], params.get("reply_markup"))
                return {"ok": True, "result": {"message_id": mid, "chat": {"id": params["chat_id"], "type": "private"},
                                               "date": int(time.time()), "text": params["text"]}}
            if method == "editMessageText":
                self.react(params["message_id"], params["text"], params.get("reply_markup"))
                return {"ok": True, "result": True}
            if method in ("answerCallbackQuery", "sendChatAction"):
                return {"ok": True, "result": True}
            return {"ok": False, "error_code": 404, "description": f"method {method} not found"}


def make_handler(server: FakeBaleServer):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            prefix = f"/bot{TOKEN}/"
            assert self.path.startswith(prefix), self.path
            method = self.path[len(prefix):]
            length = int(self.headers.get("Content-Length", 0))
            params = json.loads(self.rfile.read(length) or b"{}")
            if method == "getUpdates" and not server.updates:
                time.sleep(min(float(params.get("timeout", 0)), 0.2))   # شبیه‌سازی long polling
            body = json.dumps(server.handle(method, params)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:   # ساکت
            pass

    return Handler


@pytest.mark.asyncio
async def test_full_cpu_game_over_real_http():
    fake = FakeBaleServer()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fake))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    settings = Settings(token=TOKEN, api_base=f"http://127.0.0.1:{port}", poll_timeout=1,
                        cpu_delay=0.01, housekeeping_interval=0.2)
    api = BaleAPI(TOKEN, settings.api_base, poll_timeout=1)
    bot = GameBot(api, settings)

    async def stop_when_done() -> None:
        deadline = time.monotonic() + 15
        while not fake.done and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)      # اجازه بده آخرین ویرایش‌ها برسند
        bot.stop()

    try:
        await asyncio.wait_for(asyncio.gather(bot.run(), stop_when_done()), timeout=30)
    finally:
        await api.close()
        httpd.shutdown()

    assert fake.done, "بازی به پایان نرسید"
    methods = [e["method"] for e in fake.log]
    assert methods[:2] == ["getMe", "deleteWebhook"]
    assert "sendMessage" in methods and "editMessageText" in methods and "answerCallbackQuery" in methods
    game = bot.games.get(1)
    assert game is not None and not game.is_active
    assert game.result != game.symbol_of(USER)          # کامپیوتر سخت نمی‌بازد
    last_edit = [e for e in fake.log if e["method"] == "editMessageText"][-1]
    assert "g:again:1" in json.dumps(last_edit["reply_markup"], ensure_ascii=False)
