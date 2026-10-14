"""هستهٔ ربات: حلقهٔ دریافت آپدیت (Long Polling)، هندلرها، مچ‌میکینگ و رندر تخته.

جریان کلی:
    /start ─▶ منو ─▶ (صف حریف آنلاین | انتخاب سطح کامپیوتر) ─▶ تختهٔ بازی (پیام با دکمه‌های شیشه‌ای)
    کلیک روی خانه ─▶ callback_query ─▶ اعتبارسنجی ─▶ به‌روزرسانی وضعیت ─▶ editMessageText برای هر دو بازیکن

همهٔ تغییرات وضعیت زیر یک قفل سراسری انجام می‌شود تا کلیک‌های هم‌زمان مشکلی ایجاد نکنند.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
import json
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from . import keyboards as kb
from . import texts as T
from .bale_api import BaleAPI, BaleAPIError
from .config import Settings
from .matchmaking import (CPU, REASON_RESIGN, REASON_TIMEOUT, Game, GameManager, Matchmaker,
                          PlayerId)
from .tictactoe import LEVELS, choose_move, other

log = logging.getLogger(__name__)

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class GameBot:
    def __init__(self, api: BaleAPI, settings: Settings, *, clock: Clock = time.monotonic,
                 sleep: Sleep = asyncio.sleep, rng: Optional[random.Random] = None) -> None:
        self.api = api
        self.settings = settings
        self.clock = clock
        self.sleep = sleep
        self.rng = rng or random.Random()

        self.matchmaker = Matchmaker()
        self.games = GameManager()
        self.names: Dict[int, str] = {}            # chat_id -> نام نمایشی
        self.chat_of_user: Dict[int, int] = {}     # user_id -> chat_id (برای callback بدون message)
        self.waiting_msgs: Dict[int, int] = {}     # chat_id -> message_id پیام «در انتظار حریف»
        self._rendered: Dict[Tuple[int, int], Tuple[str, str]] = {}   # (chat, msg) -> آخرین محتوای ارسالی

        self._lock = asyncio.Lock()
        self._offset: Optional[int] = None
        self._running = False
        self.me: Dict[str, Any] = {}

    # ===================================================================== run
    async def run(self) -> None:
        """راه‌اندازی: getMe، حذف وب‌هوک، سپس حلقهٔ Long Polling + تسک پس‌زمینه."""
        self.me = await self.api.get_me()
        log.info("logged in as @%s (id=%s)", self.me.get("username"), self.me.get("id"))
        try:
            await self.api.delete_webhook()
        except BaleAPIError as exc:   # اگر وب‌هوکی نبوده باشد ممکن است خطا بدهد؛ مهم نیست
            log.debug("deleteWebhook: %s", exc)

        self._running = True
        housekeeper = asyncio.create_task(self._housekeeping_loop(), name="housekeeping")
        backoff = 1.0
        try:
            while self._running:
                try:
                    updates = await self.api.get_updates(offset=self._offset)
                    backoff = 1.0
                except BaleAPIError as exc:
                    log.error("getUpdates failed: %s — retry in %.0fs", exc, backoff)
                    await self.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                for upd in updates:
                    self._offset = max(self._offset or 0, int(upd["update_id"]) + 1)
                    asyncio.create_task(self._safe_handle(upd))
        finally:
            self._running = False
            housekeeper.cancel()

    def stop(self) -> None:
        self._running = False

    async def _safe_handle(self, update: Dict[str, Any]) -> None:
        try:
            await self.handle_update(update)
        except Exception:  # noqa: BLE001 — هیچ آپدیتی نباید ربات را از پا بیندازد
            log.exception("unhandled error in update %s", update.get("update_id"))

    # ================================================================ dispatch
    async def handle_update(self, update: Dict[str, Any]) -> None:
        if "message" in update:
            await self._on_message(update["message"])
        elif "callback_query" in update:
            await self._on_callback(update["callback_query"])
        # edited_message / pre_checkout_query: در این ربات کاربردی ندارند.

    async def _on_message(self, msg: Dict[str, Any]) -> None:
        chat = msg.get("chat") or {}
        if chat.get("type", "private") != "private":
            return                                   # فقط چت خصوصی
        chat_id = int(chat["id"])
        sender = msg.get("from") or {}
        if "id" in sender:
            self.chat_of_user[int(sender["id"])] = chat_id
        self._remember_name(chat_id, sender)

        text = (msg.get("text") or "").strip()
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""

        async with self._lock:
            if command == "/start":
                await self._cmd_start(chat_id)
            elif command == "/help":
                await self.api.send_message(chat_id, self._help_text(), kb.back_to_menu())
            elif command == "/cancel":
                await self._cmd_cancel(chat_id)
            elif text:
                await self.api.send_message(chat_id, T.UNKNOWN_TEXT, kb.main_menu())

    async def _on_callback(self, cq: Dict[str, Any]) -> None:
        sender = cq.get("from") or {}
        user_id = int(sender.get("id", 0))
        message = cq.get("message") or {}
        chat_id = int(((message.get("chat") or {}).get("id")) or self.chat_of_user.get(user_id) or user_id)
        message_id = message.get("message_id")
        self._remember_name(chat_id, sender)
        self.chat_of_user.setdefault(user_id, chat_id)

        data = str(cq.get("data") or "")
        parts = data.split(":")
        kind = parts[0]

        cpu_followup: Optional[Game] = None
        async with self._lock:
            if data == "noop":
                await self._answer(cq, chat_id)
            elif kind == "menu":
                await self._cb_menu(cq, chat_id, message_id, parts[1] if len(parts) > 1 else "home")
            elif kind == "cpu" and len(parts) == 2 and parts[1] in LEVELS:
                await self._cb_start_cpu(cq, chat_id, message_id, parts[1])
            elif data == "q:cancel":
                await self._cb_cancel_queue(cq, chat_id, message_id)
            elif kind == "mv" and len(parts) == 3:
                cpu_followup = await self._cb_move(cq, chat_id, int(parts[1]), int(parts[2]))
            elif kind == "g" and len(parts) == 3 and parts[1] == "resign":
                await self._cb_resign(cq, chat_id, int(parts[2]))
            elif kind == "g" and len(parts) == 3 and parts[1] == "again":
                await self._cb_rematch(cq, chat_id, int(parts[2]), message_id)
            else:
                await self._answer(cq, chat_id)

        if cpu_followup is not None:
            await self._cpu_turn(cpu_followup)

    # ================================================================ commands
    async def _cmd_start(self, chat_id: int) -> None:
        game = self.games.for_player(chat_id)
        if game and game.is_active:
            # کاربر پیام تخته را گم کرده؛ تختهٔ جدید بفرست.
            game.message_ids.pop(chat_id, None)
            await self._render(game)
            return
        if self.matchmaker.in_queue(chat_id):
            await self.api.send_message(chat_id, T.WAITING, kb.waiting())
            return
        await self.api.send_message(chat_id, T.WELCOME.format(name=self.names.get(chat_id, "")),
                                    kb.main_menu())

    async def _cmd_cancel(self, chat_id: int) -> None:
        if self.matchmaker.leave(chat_id):
            self.waiting_msgs.pop(chat_id, None)
            await self.api.send_message(chat_id, T.QUEUE_CANCELLED, kb.main_menu())
            return
        game = self.games.for_player(chat_id)
        if game and game.is_active:
            await self._resign(game, chat_id)
            return
        await self.api.send_message(chat_id, T.NOT_IN_QUEUE_OR_GAME, kb.main_menu())

    # ================================================================ callbacks
    async def _cb_menu(self, cq: Dict[str, Any], chat_id: int, message_id: Optional[int], item: str) -> None:
        if item == "human":
            await self._join_queue(cq, chat_id, message_id)
        elif item == "cpu":
            if self._busy_notice(chat_id):
                await self._answer(cq, chat_id, self._busy_notice(chat_id), alert=True)
                return
            await self._answer(cq, chat_id)
            await self._edit_or_send(chat_id, message_id, T.CHOOSE_LEVEL, kb.cpu_levels())
        elif item == "help":
            await self._answer(cq, chat_id)
            await self._edit_or_send(chat_id, message_id, self._help_text(), kb.back_to_menu())
        else:  # home
            await self._answer(cq, chat_id)
            await self._edit_or_send(chat_id, message_id, T.MENU, kb.main_menu())

    async def _join_queue(self, cq: Dict[str, Any], chat_id: int, message_id: Optional[int]) -> None:
        notice = self._busy_notice(chat_id)
        if notice:
            await self._answer(cq, chat_id, notice, alert=True)
            return
        pair = self.matchmaker.join(chat_id, self.clock())
        if pair is None:
            await self._answer(cq, chat_id)
            mid = await self._edit_or_send(chat_id, message_id, T.WAITING, kb.waiting())
            if mid:
                self.waiting_msgs[chat_id] = mid
            return

        first, second = pair
        await self._answer(cq, chat_id, T.MATCH_FOUND)
        first_mid = self.waiting_msgs.pop(first, None)
        msg_ids = {}
        if first_mid:
            msg_ids[first] = first_mid
        if message_id:
            msg_ids[second] = message_id
        await self._start_game(first, second, message_ids=msg_ids)

    async def _cb_cancel_queue(self, cq: Dict[str, Any], chat_id: int, message_id: Optional[int]) -> None:
        self.matchmaker.leave(chat_id)
        self.waiting_msgs.pop(chat_id, None)
        await self._answer(cq, chat_id)
        await self._edit_or_send(chat_id, message_id, T.QUEUE_CANCELLED + "\n\n" + T.MENU, kb.main_menu())

    async def _cb_start_cpu(self, cq: Dict[str, Any], chat_id: int, message_id: Optional[int], level: str) -> None:
        notice = self._busy_notice(chat_id)
        if notice:
            await self._answer(cq, chat_id, notice, alert=True)
            return
        await self._answer(cq, chat_id)
        # نماد انسان تصادفی است؛ اگر کامپیوتر X باشد اول حرکت می‌کند.
        human_is_x = self.rng.random() < 0.5
        x, o = (chat_id, CPU) if human_is_x else (CPU, chat_id)
        msg_ids = {chat_id: message_id} if message_id else {}
        game = await self._start_game(x, o, cpu_level=level, message_ids=msg_ids)
        if game.current_player == CPU:
            await self._cpu_move_now(game)

    async def _cb_move(self, cq: Dict[str, Any], chat_id: int, game_id: int, idx: int) -> Optional[Game]:
        """حرکت انسان. اگر بعد از آن نوبت کامپیوتر باشد، بازی را برمی‌گرداند تا بیرون از قفل اجرا شود."""
        game = self.games.get(game_id)
        if game is None or not game.is_active:
            await self._answer(cq, chat_id, T.GAME_NOT_FOUND)
            return None
        if game.symbol_of(chat_id) is None:
            await self._answer(cq, chat_id, T.NOT_YOUR_GAME)
            return None
        if not game.is_turn_of(chat_id):
            await self._answer(cq, chat_id, T.NOT_YOUR_TURN)
            return None
        if not game.board.is_legal(idx):
            await self._answer(cq, chat_id, T.CELL_TAKEN)
            return None

        game.apply_move(chat_id, idx, self.clock())
        await self._answer(cq, chat_id)
        if not game.is_active:
            self.games.release_players(game)
        await self._render(game)
        if game.is_active and game.current_player == CPU:
            return game
        return None

    async def _cb_resign(self, cq: Dict[str, Any], chat_id: int, game_id: int) -> None:
        game = self.games.get(game_id)
        if game is None or not game.is_active or game.symbol_of(chat_id) is None:
            await self._answer(cq, chat_id, T.GAME_NOT_FOUND)
            return
        await self._answer(cq, chat_id)
        await self._resign(game, chat_id)

    async def _cb_rematch(self, cq: Dict[str, Any], chat_id: int, game_id: int, message_id: Optional[int]) -> None:
        game = self.games.get(game_id)
        if game is None or game.is_active or game.symbol_of(chat_id) is None:
            await self._answer(cq, chat_id, T.GAME_NOT_FOUND)
            return
        notice = self._busy_notice(chat_id)
        if notice:
            await self._answer(cq, chat_id, notice, alert=True)
            return

        my_sym = game.symbol_of(chat_id)
        opp = game.player(other(my_sym))

        if opp == CPU:
            await self._answer(cq, chat_id)
            # تعویض نماد: اگر دفعهٔ قبل X بودی حالا O می‌شوی.
            x, o = (CPU, chat_id) if my_sym == "X" else (chat_id, CPU)
            msg_ids = {chat_id: message_id or game.message_ids.get(chat_id)}
            self.games.remove(game.id)
            new = await self._start_game(x, o, cpu_level=game.cpu_level, message_ids=msg_ids)
            if new.current_player == CPU:
                await self._cpu_move_now(new)
            return

        assert isinstance(opp, int)
        if self._busy_notice(opp) or opp not in self.names:
            await self._answer(cq, chat_id, T.REMATCH_UNAVAILABLE, alert=True)
            return

        game.rematch_votes.add(chat_id)
        if opp in game.rematch_votes:
            await self._answer(cq, chat_id)
            x, o = game.player("O"), game.player("X")       # تعویض نماد
            msg_ids = dict(game.message_ids)
            if message_id:
                msg_ids[chat_id] = message_id
            self.games.remove(game.id)
            await self._start_game(x, o, message_ids=msg_ids)
        else:
            await self._answer(cq, chat_id, T.REMATCH_WAIT)
            await self._render(game, notes={opp: T.REMATCH_OPPONENT_WANTS, chat_id: T.REMATCH_WAIT})

    # ================================================================ game flow
    async def _start_game(self, x: PlayerId, o: PlayerId, cpu_level: Optional[str] = None,
                          message_ids: Optional[Dict[int, Optional[int]]] = None) -> Game:
        game = self.games.create(x, o, cpu_level=cpu_level, now=self.clock())
        for cid, mid in (message_ids or {}).items():
            if mid:
                game.message_ids[cid] = mid
        log.info("game #%d started: X=%s O=%s level=%s", game.id, x, o, cpu_level)
        await self._render(game)
        return game

    async def _cpu_turn(self, game: Game) -> None:
        """نوبت کامپیوتر بعد از حرکت انسان؛ مکث «فکر کردن» خارج از قفل انجام می‌شود."""
        if self.settings.cpu_delay > 0:
            human = game.human_players()[0]
            try:
                await self.api.send_chat_action(human, "typing")
            except BaleAPIError:
                pass
            await self.sleep(self.settings.cpu_delay)
        async with self._lock:
            if game.is_active and game.current_player == CPU:
                await self._cpu_move_now(game)

    async def _cpu_move_now(self, game: Game) -> None:
        idx = choose_move(game.board, game.turn, game.cpu_level or "hard", self.rng)
        game.apply_move(CPU, idx, self.clock())
        if not game.is_active:
            self.games.release_players(game)
        await self._render(game)

    async def _resign(self, game: Game, chat_id: int) -> None:
        my_sym = game.symbol_of(chat_id)
        assert my_sym is not None
        game.finish(winner_symbol=other(my_sym), reason=REASON_RESIGN, now=self.clock())
        self.games.release_players(game)
        notes: Dict[int, str] = {chat_id: T.RESIGNED_YOU}
        opp = game.player(other(my_sym))
        if isinstance(opp, int):
            notes[opp] = T.RESIGNED_OPPONENT
        await self._render(game, notes=notes)

    async def _timeout(self, game: Game) -> None:
        loser = game.current_player
        game.finish(winner_symbol=other(game.turn), reason=REASON_TIMEOUT, now=self.clock())
        self.games.release_players(game)
        notes: Dict[int, str] = {}
        if isinstance(loser, int):
            notes[loser] = T.TIMEOUT_YOU
        opp = game.opponent_of(loser)
        if isinstance(opp, int):
            notes[opp] = T.TIMEOUT_OPPONENT
        await self._render(game, notes=notes)

    # ================================================================ rendering
    def board_text(self, game: Game, chat_id: int, note: Optional[str] = None) -> str:
        my_sym = game.symbol_of(chat_id) or "X"
        opp = game.player(other(my_sym))
        lines = [T.BOARD_HEADER.format(game_id=game.id)]
        if opp == CPU:
            lines.append(T.BOARD_PLAYERS_CPU.format(
                me_sym=T.SYMBOLS[my_sym], opp_sym=T.SYMBOLS[other(my_sym)],
                level=T.LEVEL_NAMES.get(game.cpu_level or "hard", "")))
        else:
            lines.append(T.BOARD_PLAYERS_HUMAN.format(
                me_sym=T.SYMBOLS[my_sym], opp_sym=T.SYMBOLS[other(my_sym)],
                opp_name=T.safe(self.names.get(int(opp), ""))))
        lines.append("")
        if game.is_active:
            if game.current_player == chat_id:
                lines.append(T.TURN_YOU)
            elif game.current_player == CPU:
                lines.append(T.TURN_CPU)
            else:
                lines.append(T.TURN_OPPONENT)
        else:
            if game.result == "draw":
                lines.append(T.RESULT_DRAW)
            elif game.result == my_sym:
                lines.append(T.RESULT_WIN)
            else:
                lines.append(T.RESULT_LOSE)
        if note:
            lines.append(note)
        return "\n".join(lines)

    async def _render(self, game: Game, notes: Optional[Dict[int, str]] = None) -> None:
        """تختهٔ هر بازیکن انسانی را ویرایش (یا در صورت نبود پیام، ارسال) می‌کند."""
        notes = notes or {}
        for cid in game.human_players():
            text = self.board_text(game, cid, notes.get(cid))
            markup = kb.game_board(game.board, game.id) if game.is_active \
                else kb.finished_board(game.board, game.id, allow_rematch=True)
            mid = await self._edit_or_send(cid, game.message_ids.get(cid), text, markup)
            if mid:
                game.message_ids[cid] = mid

    async def _edit_or_send(self, chat_id: int, message_id: Optional[int], text: str,
                            markup: Optional[dict]) -> Optional[int]:
        """اگر message_id داشته باشیم ویرایش می‌کند؛ در غیر این صورت (یا در صورت خطا) پیام جدید می‌فرستد.
        شناسهٔ پیامِ نهایی را برمی‌گرداند."""
        signature = (text, json.dumps(markup, sort_keys=True, ensure_ascii=False))
        if message_id:
            if self._rendered.get((chat_id, message_id)) == signature:
                return message_id            # محتوا تغییری نکرده؛ ویرایش تکراری نفرست
            try:
                await self.api.edit_message_text(chat_id, message_id, text, markup)
                self._rendered[(chat_id, message_id)] = signature
                return message_id
            except BaleAPIError as exc:
                if "not modified" in str(exc.description).lower():
                    return message_id
                log.warning("editMessageText failed for chat %s msg %s: %s — sending new", chat_id, message_id, exc)
        try:
            sent = await self.api.send_message(chat_id, text, markup)
        except BaleAPIError as exc:
            log.error("sendMessage failed for chat %s: %s", chat_id, exc)
            return None
        new_id = (sent or {}).get("message_id")
        if new_id:
            self._rendered[(chat_id, new_id)] = signature
        return new_id

    async def _answer(self, cq: Dict[str, Any], chat_id: int, text: Optional[str] = None,
                      alert: bool = False) -> None:
        """پاسخ به callback؛ برای کلاینت‌های قدیمی (شناسهٔ با «1» شروع‌شده) متن را به‌صورت پیام می‌فرستد."""
        cq_id = str(cq.get("id", ""))
        legacy = cq_id.startswith("1")
        try:
            await self.api.answer_callback_query(cq_id, text=None if legacy else text,
                                                 show_alert=(alert or None) if not legacy else None)
        except BaleAPIError as exc:
            log.debug("answerCallbackQuery failed (%s): %s", cq_id, exc)
        if legacy and text:
            try:
                await self.api.send_message(chat_id, text)
            except BaleAPIError as exc:
                log.debug("legacy fallback message failed: %s", exc)

    # ================================================================ helpers
    def _remember_name(self, chat_id: int, user: Dict[str, Any]) -> None:
        name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p).strip()
        if name:
            self.names[chat_id] = T.safe(name)

    def _busy_notice(self, chat_id: int) -> Optional[str]:
        if self.matchmaker.in_queue(chat_id):
            return T.ALREADY_IN_QUEUE
        game = self.games.for_player(chat_id)
        if game and game.is_active:
            return T.ALREADY_IN_GAME
        return None

    def _help_text(self) -> str:
        return T.HELP.format(turn_timeout=int(self.settings.turn_timeout))

    # ================================================================ housekeeping
    async def housekeeping_once(self) -> None:
        """تایم‌اوت صف و نوبت + پاک‌سازی بازی‌های تمام‌شدهٔ قدیمی. (در تست‌ها مستقیم صدا زده می‌شود.)"""
        now = self.clock()
        async with self._lock:
            for cid in self.matchmaker.pop_expired(now, self.settings.queue_timeout):
                mid = self.waiting_msgs.pop(cid, None)
                await self._edit_or_send(cid, mid, T.QUEUE_TIMEOUT, kb.queue_timeout())

            for game in self.games.active_games():
                if game.current_player == CPU:
                    continue
                if now - game.last_move_at >= self.settings.turn_timeout:
                    log.info("game #%d timed out (player %s)", game.id, game.current_player)
                    await self._timeout(game)

            for game in self.games.finished_games():
                if game.finished_at is not None and now - game.finished_at > 3600:
                    self.games.remove(game.id)

    async def _housekeeping_loop(self) -> None:
        while True:
            await self.sleep(self.settings.housekeeping_interval)
            try:
                await self.housekeeping_once()
            except Exception:  # noqa: BLE001
                log.exception("housekeeping error")
