"""تست جریان کامل ربات با API جعلی: منو، صف، مچ‌میکینگ، بازی دونفره، بازی با کامپیوتر، تایم‌اوت‌ها."""
from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, Optional

import pytest

from bot import texts as T
from bot.app import GameBot
from bot.config import Settings
from bot.matchmaking import CPU
from bot.tictactoe import other
from tests.fake_api import FakeAPI, button_texts, callback_datas

ALICE, BOB, CAROL = 1001, 1002, 1003


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Harness:
    """ابزار کمکی برای شبیه‌سازی آپدیت‌های بله."""

    def __init__(self, cpu_delay: float = 0.0, fail_edit_ids=(), seed: int = 7) -> None:
        self.api = FakeAPI(fail_edit_ids=fail_edit_ids)
        self.clock = FakeClock()
        self.sleeps: list = []
        self.settings = Settings(token="test", cpu_delay=cpu_delay, turn_timeout=60, queue_timeout=120)

        async def fake_sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        self.bot = GameBot(self.api, self.settings, clock=self.clock, sleep=fake_sleep,
                           rng=random.Random(seed))
        self._update_id = 0
        self._cq_id = 5000

    def _next(self) -> int:
        self._update_id += 1
        return self._update_id

    async def text(self, chat_id: int, text: str, name: str = "کاربر") -> None:
        await self.bot.handle_update({
            "update_id": self._next(),
            "message": {
                "message_id": 1, "date": 0, "text": text,
                "chat": {"id": chat_id, "type": "private", "first_name": name},
                "from": {"id": chat_id, "is_bot": False, "first_name": name},
            },
        })

    async def start(self, chat_id: int, name: str) -> int:
        """ارسال /start و برگرداندن شناسهٔ پیام منو."""
        await self.text(chat_id, "/start", name)
        return self.api.last_sent_id(chat_id)

    async def click(self, chat_id: int, message_id: Optional[int], data: str,
                    cq_id: Optional[str] = None, name: Optional[str] = None) -> None:
        self._cq_id += 1
        sender: Dict[str, Any] = {"id": chat_id, "is_bot": False}
        if name:
            sender["first_name"] = name
        cq: Dict[str, Any] = {"id": cq_id or str(self._cq_id), "from": sender, "data": data}
        if message_id is not None:
            cq["message"] = {"message_id": message_id, "date": 0,
                             "chat": {"id": chat_id, "type": "private"}}
        await self.bot.handle_update({"update_id": self._next(), "callback_query": cq})

    def board(self, chat_id: int, message_id: int) -> Dict[str, Any]:
        return self.api.content(chat_id, message_id)

    def cells(self, chat_id: int, message_id: int) -> list:
        return [t for row in button_texts(self.board(chat_id, message_id)["reply_markup"])[:3] for t in row]


async def match_two(h: Harness):
    """آلیس و باب را /start و جفت می‌کند؛ شناسهٔ پیام تختهٔ هر دو را برمی‌گرداند."""
    a_menu = await h.start(ALICE, "Alice")
    b_menu = await h.start(BOB, "Bob")
    await h.click(ALICE, a_menu, "menu:human")
    assert h.board(ALICE, a_menu)["text"] == T.WAITING
    assert h.bot.matchmaker.in_queue(ALICE)
    await h.click(BOB, b_menu, "menu:human")
    game = h.bot.games.for_player(ALICE)
    assert game is not None and game is h.bot.games.for_player(BOB)
    assert game.players == {"X": ALICE, "O": BOB}      # نفر اول صف X است و شروع می‌کند
    assert game.message_ids == {ALICE: a_menu, BOB: b_menu}   # همان پیام‌ها به تخته تبدیل شده‌اند
    return game, a_menu, b_menu


# =========================================================================== tests
@pytest.mark.asyncio
async def test_start_sends_menu_with_name():
    h = Harness()
    mid = await h.start(ALICE, "علی")
    content = h.board(ALICE, mid)
    assert "علی" in content["text"]
    assert callback_datas(content["reply_markup"]) == ["menu:human", "menu:cpu", "menu:help"]


@pytest.mark.asyncio
async def test_menu_navigation_edits_same_message():
    h = Harness()
    mid = await h.start(ALICE, "Alice")
    await h.click(ALICE, mid, "menu:help")
    assert "راهنما" in h.board(ALICE, mid)["text"]
    await h.click(ALICE, mid, "menu:home")
    assert h.board(ALICE, mid)["text"] == T.MENU
    await h.click(ALICE, mid, "menu:cpu")
    assert callback_datas(h.board(ALICE, mid)["reply_markup"])[:3] == ["cpu:easy", "cpu:medium", "cpu:hard"]
    # هر کلیک باید answerCallbackQuery داشته باشد
    assert len(h.api.calls_of("answerCallbackQuery")) == 3
    # هیچ پیام جدیدی ارسال نشده (فقط ویرایش)
    assert len(h.api.calls_of("sendMessage")) == 1


@pytest.mark.asyncio
async def test_two_players_match_play_and_win():
    h = Harness()
    game, a_mid, b_mid = await match_two(h)

    assert T.TURN_YOU in h.board(ALICE, a_mid)["text"]
    assert T.TURN_OPPONENT in h.board(BOB, b_mid)["text"]
    assert "Alice" in h.board(BOB, b_mid)["text"] and "Bob" in h.board(ALICE, a_mid)["text"]
    assert callback_datas(h.board(ALICE, a_mid)["reply_markup"])[:9] == [f"mv:{game.id}:{i}" for i in range(9)]

    # باب خارج از نوبت کلیک می‌کند
    await h.click(BOB, b_mid, f"mv:{game.id}:4")
    assert h.api.last_answer()["text"] == T.NOT_YOUR_TURN
    assert game.move_count == 0

    # حرکت‌ها: آلیس 0، باب 3، آلیس 1، باب 4، آلیس 2 → برد آلیس
    for who, mid, idx in [(ALICE, a_mid, 0), (BOB, b_mid, 3), (ALICE, a_mid, 1), (BOB, b_mid, 4)]:
        await h.click(who, mid, f"mv:{game.id}:{idx}")
        # تختهٔ هر دو نفر هم‌زمان به‌روز می‌شود
        assert h.cells(ALICE, a_mid) == h.cells(BOB, b_mid)

    # خانهٔ پر
    await h.click(ALICE, a_mid, f"mv:{game.id}:3")
    assert h.api.last_answer()["text"] == T.CELL_TAKEN

    await h.click(ALICE, a_mid, f"mv:{game.id}:2")
    assert not game.is_active and game.result == "X"
    assert T.RESULT_WIN in h.board(ALICE, a_mid)["text"]
    assert T.RESULT_LOSE in h.board(BOB, b_mid)["text"]
    assert h.cells(ALICE, a_mid) == ["❌", "❌", "❌", "⭕", "⭕", "⬜", "⬜", "⬜", "⬜"]
    # تختهٔ پایان‌یافته: خانه‌ها noop و دکمهٔ بازی مجدد
    datas = callback_datas(h.board(BOB, b_mid)["reply_markup"])
    assert datas[:9] == ["noop"] * 9 and f"g:again:{game.id}" in datas
    # بازیکن‌ها آزاد شده‌اند
    assert h.bot.games.for_player(ALICE) is None and h.bot.games.for_player(BOB) is None

    # حرکت روی بازی تمام‌شده
    await h.click(BOB, b_mid, f"mv:{game.id}:5")
    assert h.api.last_answer()["text"] == T.GAME_NOT_FOUND


@pytest.mark.asyncio
async def test_rematch_requires_both_votes_and_swaps_symbols():
    h = Harness()
    game, a_mid, b_mid = await match_two(h)
    await h.click(ALICE, a_mid, f"g:resign:{game.id}")
    assert not game.is_active and game.result == "O"
    assert T.RESIGNED_YOU in h.board(ALICE, a_mid)["text"]
    assert T.RESIGNED_OPPONENT in h.board(BOB, b_mid)["text"]

    await h.click(ALICE, a_mid, f"g:again:{game.id}")
    assert h.api.last_answer()["text"] == T.REMATCH_WAIT
    assert T.REMATCH_OPPONENT_WANTS in h.board(BOB, b_mid)["text"]
    assert h.bot.games.for_player(ALICE) is None          # هنوز بازی جدیدی نیست

    await h.click(BOB, b_mid, f"g:again:{game.id}")
    new = h.bot.games.for_player(ALICE)
    assert new is not None and new.id != game.id and new.is_active
    assert new.players == {"X": BOB, "O": ALICE}          # نمادها عوض شده‌اند
    assert new.message_ids == {ALICE: a_mid, BOB: b_mid}  # همان پیام‌ها دوباره تخته شده‌اند
    assert T.TURN_YOU in h.board(BOB, b_mid)["text"]
    assert h.bot.games.get(game.id) is None               # بازی قبلی پاک شده


@pytest.mark.asyncio
async def test_busy_player_cannot_join_queue_or_cpu():
    h = Harness()
    game, a_mid, b_mid = await match_two(h)
    await h.click(ALICE, a_mid, "menu:human")
    ans = h.api.last_answer()
    assert ans["text"] == T.ALREADY_IN_GAME and ans["show_alert"] is True
    await h.click(ALICE, a_mid, "cpu:hard")
    assert h.api.last_answer()["text"] == T.ALREADY_IN_GAME
    # نفر سوم که در صف است هم نمی‌تواند دوباره وارد شود
    c_mid = await h.start(CAROL, "Carol")
    await h.click(CAROL, c_mid, "menu:human")
    await h.click(CAROL, c_mid, "menu:human")
    assert h.api.last_answer()["text"] == T.ALREADY_IN_QUEUE


@pytest.mark.asyncio
async def test_cancel_queue_button_and_command():
    h = Harness()
    a_mid = await h.start(ALICE, "Alice")
    await h.click(ALICE, a_mid, "menu:human")
    await h.click(ALICE, a_mid, "q:cancel")
    assert not h.bot.matchmaker.in_queue(ALICE)
    assert T.QUEUE_CANCELLED in h.board(ALICE, a_mid)["text"]

    await h.click(ALICE, a_mid, "menu:human")
    assert h.bot.matchmaker.in_queue(ALICE)
    await h.text(ALICE, "/cancel")
    assert not h.bot.matchmaker.in_queue(ALICE)
    assert h.api.calls_of("sendMessage")[-1]["text"] == T.QUEUE_CANCELLED

    await h.text(ALICE, "/cancel")
    assert h.api.calls_of("sendMessage")[-1]["text"] == T.NOT_IN_QUEUE_OR_GAME


@pytest.mark.asyncio
async def test_cancel_command_resigns_active_game():
    h = Harness()
    game, a_mid, b_mid = await match_two(h)
    await h.text(BOB, "/cancel")
    assert not game.is_active and game.result == "X"
    assert T.RESIGNED_OPPONENT in h.board(ALICE, a_mid)["text"]


@pytest.mark.asyncio
async def test_start_during_active_game_resends_board():
    h = Harness()
    game, a_mid, b_mid = await match_two(h)
    await h.start(ALICE, "Alice")
    new_mid = h.api.last_sent_id(ALICE)
    assert new_mid != a_mid and game.message_ids[ALICE] == new_mid
    assert T.TURN_YOU in h.board(ALICE, new_mid)["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
async def test_cpu_hard_never_loses(seed):
    h = Harness(seed=seed)
    rng = random.Random(seed)
    mid = await h.start(CAROL, "Carol")
    await h.click(CAROL, mid, "menu:cpu")
    await h.click(CAROL, mid, "cpu:hard")
    game = h.bot.games.for_player(CAROL)
    assert game is not None and game.is_cpu_game and game.cpu_level == "hard"
    human_sym = game.symbol_of(CAROL)
    if game.player("X") == CPU:
        assert game.move_count == 1            # کامپیوترِ X فوراً شروع کرده

    while game.is_active:
        assert game.current_player == CAROL    # با cpu_delay=0 کامپیوتر همیشه بلافاصله جواب می‌دهد
        idx = rng.choice(game.board.legal_moves())
        await h.click(CAROL, mid, f"mv:{game.id}:{idx}")

    assert game.result != human_sym            # انسان هرگز نمی‌برد
    text = h.board(CAROL, mid)["text"]
    assert (T.RESULT_DRAW in text) or (T.RESULT_LOSE in text)
    assert "سخت" in text
    # بازی مجدد با کامپیوتر فوری است و نماد عوض می‌شود
    await h.click(CAROL, mid, f"g:again:{game.id}")
    new = h.bot.games.for_player(CAROL)
    assert new is not None and new.is_active and new.symbol_of(CAROL) == other(human_sym)
    assert new.message_ids[CAROL] == mid


@pytest.mark.asyncio
async def test_cpu_delay_path_uses_typing_and_sleep():
    h = Harness(cpu_delay=0.5, seed=3)
    mid = await h.start(CAROL, "Carol")
    await h.click(CAROL, mid, "cpu:easy")
    game = h.bot.games.for_player(CAROL)
    # تا نوبت انسان شود (اگر کامپیوتر X بود، اولین حرکتش بدون مکث انجام شده)
    assert game.current_player == CAROL
    before = game.move_count
    idx = game.board.legal_moves()[0]
    await h.click(CAROL, mid, f"mv:{game.id}:{idx}")
    assert game.move_count == before + 2 or not game.is_active
    assert 0.5 in h.sleeps
    assert h.api.calls_of("sendChatAction")[-1] == {"chat_id": CAROL, "action": "typing"}


@pytest.mark.asyncio
async def test_legacy_client_callback_gets_text_as_message():
    h = Harness()
    game, a_mid, b_mid = await match_two(h)
    h.api.clear()
    await h.click(BOB, b_mid, f"mv:{game.id}:4", cq_id="1" + "7" * 10)   # شناسهٔ با «1» = کلاینت قدیمی
    ans = h.api.last_answer()
    assert ans["text"] is None                                           # متن به answer داده نمی‌شود
    assert h.api.calls_of("sendMessage")[-1] == {"chat_id": BOB, "text": T.NOT_YOUR_TURN, "reply_markup": None}


@pytest.mark.asyncio
async def test_callback_without_message_uses_known_chat():
    h = Harness()
    await h.start(ALICE, "Alice")
    await h.click(ALICE, None, "menu:human")             # callback بدون فیلد message
    assert h.bot.matchmaker.in_queue(ALICE)
    assert h.api.calls_of("sendMessage")[-1]["text"] == T.WAITING


@pytest.mark.asyncio
async def test_queue_timeout_housekeeping():
    h = Harness()
    a_mid = await h.start(ALICE, "Alice")
    await h.click(ALICE, a_mid, "menu:human")
    h.clock.now = 100
    await h.bot.housekeeping_once()
    assert h.bot.matchmaker.in_queue(ALICE)              # هنوز زود است
    h.clock.now = 125
    await h.bot.housekeeping_once()
    assert not h.bot.matchmaker.in_queue(ALICE)
    content = h.board(ALICE, a_mid)
    assert content["text"] == T.QUEUE_TIMEOUT
    assert callback_datas(content["reply_markup"]) == ["menu:human", "menu:cpu"]


@pytest.mark.asyncio
async def test_turn_timeout_housekeeping():
    h = Harness()
    game, a_mid, b_mid = await match_two(h)
    await h.click(ALICE, a_mid, f"mv:{game.id}:0")        # حالا نوبت باب
    h.clock.now = 30
    await h.bot.housekeeping_once()
    assert game.is_active
    h.clock.now = 61
    await h.bot.housekeeping_once()
    assert not game.is_active and game.result == "X" and game.end_reason == "timeout"
    assert T.TIMEOUT_YOU in h.board(BOB, b_mid)["text"]
    assert T.TIMEOUT_OPPONENT in h.board(ALICE, a_mid)["text"]
    # بازی تمام‌شده بعد از یک ساعت از حافظه پاک می‌شود
    h.clock.now = 61 + 3601
    await h.bot.housekeeping_once()
    assert h.bot.games.get(game.id) is None


@pytest.mark.asyncio
async def test_edit_failure_falls_back_to_new_message():
    h = Harness(fail_edit_ids=(100,))                     # اولین پیام (منوی آلیس) قابل ویرایش نیست
    a_mid = await h.start(ALICE, "Alice")
    assert a_mid == 100
    await h.click(ALICE, a_mid, "menu:human")
    new_mid = h.api.last_sent_id(ALICE)
    assert new_mid != a_mid
    assert h.bot.waiting_msgs[ALICE] == new_mid
    assert h.board(ALICE, new_mid)["text"] == T.WAITING


@pytest.mark.asyncio
async def test_unknown_text_and_group_messages():
    h = Harness()
    await h.text(ALICE, "سلام")
    assert h.api.calls_of("sendMessage")[-1]["text"] == T.UNKNOWN_TEXT
    h.api.clear()
    await h.bot.handle_update({"update_id": 99, "message": {
        "message_id": 5, "date": 0, "text": "/start",
        "chat": {"id": -500, "type": "group", "title": "g"},
        "from": {"id": ALICE, "is_bot": False, "first_name": "Alice"}}})
    assert h.api.calls == []                              # پیام گروه نادیده گرفته می‌شود


@pytest.mark.asyncio
async def test_markdown_characters_in_names_are_stripped():
    h = Harness()
    await h.start(ALICE, "a_b*c")
    assert h.bot.names[ALICE] == "abc"


@pytest.mark.asyncio
async def test_run_loop_dispatches_updates_and_stops():
    """حلقهٔ run با API جعلی: یک آپدیت می‌دهد، بعد ربات را متوقف می‌کند."""
    h = Harness()
    updates = [[{"update_id": 1, "message": {"message_id": 1, "date": 0, "text": "/start",
                                             "chat": {"id": ALICE, "type": "private"},
                                             "from": {"id": ALICE, "is_bot": False, "first_name": "A"}}}]]

    async def fake_get_updates(offset=None, limit=100, timeout=None):
        h.api.calls.append(("getUpdates", {"offset": offset}))
        if updates:
            return updates.pop(0)
        h.bot.stop()
        return []

    h.api.get_updates = fake_get_updates          # type: ignore[assignment]
    await asyncio.wait_for(h.bot.run(), timeout=5)
    await asyncio.sleep(0)                          # اجازه بده تسک هندلر تمام شود
    assert h.bot.me["username"] == "doozbot"
    assert [c["offset"] for c in h.api.calls_of("getUpdates")] == [None, 2]
    assert h.api.calls_of("sendMessage")[-1]["chat_id"] == ALICE


@pytest.mark.asyncio
async def test_identical_edit_is_skipped():
    h = Harness()
    mid = await h.start(ALICE, "Alice")
    await h.click(ALICE, mid, "menu:home")
    n = len(h.api.calls_of("editMessageText"))
    await h.click(ALICE, mid, "menu:home")               # همان محتوا → بدون درخواست ویرایش
    assert len(h.api.calls_of("editMessageText")) == n
    assert len(h.api.calls_of("sendMessage")) == 1
