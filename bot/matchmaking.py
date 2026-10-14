"""صف انتظار (Matchmaker) و مدیریت بازی‌های فعال (GameManager).

مستقل از بله؛ فقط با شناسهٔ چت بازیکن‌ها (int) کار می‌کند. حریف کامپیوتری با ثابت ``CPU`` مشخص می‌شود.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Union

from .tictactoe import Board, O, X, other

CPU = "cpu"
PlayerId = Union[int, str]   # chat_id یا CPU

STATUS_ACTIVE = "active"
STATUS_FINISHED = "finished"

REASON_WIN = "win"
REASON_DRAW = "draw"
REASON_RESIGN = "resign"
REASON_TIMEOUT = "timeout"
REASON_LEFT = "left"


@dataclass
class Game:
    id: int
    players: Dict[str, PlayerId]                 # {"X": chat_id | CPU, "O": chat_id | CPU}
    board: Board = field(default_factory=Board)
    turn: str = X
    status: str = STATUS_ACTIVE
    result: Optional[str] = None                 # "X" | "O" | "draw"
    end_reason: Optional[str] = None
    cpu_level: Optional[str] = None
    message_ids: Dict[int, int] = field(default_factory=dict)   # chat_id -> message_id تختهٔ هر بازیکن
    created_at: float = 0.0
    last_move_at: float = 0.0
    finished_at: Optional[float] = None
    rematch_votes: Set[int] = field(default_factory=set)
    move_count: int = 0

    # ---------------------------------------------------------------- queries
    def symbol_of(self, chat_id: PlayerId) -> Optional[str]:
        for sym, pid in self.players.items():
            if pid == chat_id:
                return sym
        return None

    def player(self, symbol: str) -> PlayerId:
        return self.players[symbol]

    def opponent_of(self, chat_id: PlayerId) -> Optional[PlayerId]:
        sym = self.symbol_of(chat_id)
        return None if sym is None else self.players[other(sym)]

    def human_players(self) -> List[int]:
        return [pid for pid in self.players.values() if isinstance(pid, int)]

    @property
    def is_cpu_game(self) -> bool:
        return CPU in self.players.values()

    @property
    def current_player(self) -> PlayerId:
        return self.players[self.turn]

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    def is_turn_of(self, chat_id: PlayerId) -> bool:
        return self.is_active and self.current_player == chat_id

    # ---------------------------------------------------------------- actions
    def apply_move(self, chat_id: PlayerId, idx: int, now: float) -> None:
        """حرکت را اعمال می‌کند؛ در صورت نامعتبر بودن ValueError می‌دهد. نتیجهٔ بازی را هم به‌روز می‌کند."""
        if not self.is_active:
            raise ValueError("game is not active")
        if not self.is_turn_of(chat_id):
            raise ValueError("not your turn")
        self.board.play(idx, self.turn)      # ValueError اگر خانه پر باشد
        self.move_count += 1
        self.last_move_at = now
        res = self.board.result()
        if res is not None:
            self.status = STATUS_FINISHED
            self.result = res
            self.end_reason = REASON_DRAW if res == "draw" else REASON_WIN
            self.finished_at = now
        else:
            self.turn = other(self.turn)

    def finish(self, winner_symbol: Optional[str], reason: str, now: float) -> None:
        if not self.is_active:
            return
        self.status = STATUS_FINISHED
        self.result = winner_symbol if winner_symbol else "draw"
        self.end_reason = reason
        self.finished_at = now


class Matchmaker:
    """صف FIFO؛ به‌محض ورود نفر دوم، جفت می‌سازد."""

    def __init__(self) -> None:
        self._queue: "OrderedDict[int, float]" = OrderedDict()   # chat_id -> زمان ورود

    def __len__(self) -> int:
        return len(self._queue)

    def in_queue(self, chat_id: int) -> bool:
        return chat_id in self._queue

    def join(self, chat_id: int, now: Optional[float] = None) -> Optional[Tuple[int, int]]:
        """بازیکن را به صف اضافه می‌کند. اگر حریفی منتظر بود، زوج ``(first, second)`` برمی‌گرداند."""
        now = time.monotonic() if now is None else now
        if chat_id in self._queue:
            return None
        if self._queue:
            first, _ = self._queue.popitem(last=False)
            return (first, chat_id)
        self._queue[chat_id] = now
        return None

    def leave(self, chat_id: int) -> bool:
        return self._queue.pop(chat_id, None) is not None

    def waiting_since(self, chat_id: int) -> Optional[float]:
        return self._queue.get(chat_id)

    def pop_expired(self, now: float, max_wait: float) -> List[int]:
        expired = [cid for cid, t in self._queue.items() if now - t >= max_wait]
        for cid in expired:
            del self._queue[cid]
        return expired


class GameManager:
    def __init__(self) -> None:
        self._games: Dict[int, Game] = {}
        self._by_player: Dict[int, int] = {}      # chat_id -> game_id (فقط بازی‌های فعال)
        self._next_id = 1

    def create(self, x_player: PlayerId, o_player: PlayerId, cpu_level: Optional[str] = None,
               now: Optional[float] = None) -> Game:
        now = time.monotonic() if now is None else now
        game = Game(id=self._next_id, players={X: x_player, O: o_player}, cpu_level=cpu_level,
                    created_at=now, last_move_at=now)
        self._next_id += 1
        self._games[game.id] = game
        for pid in game.human_players():
            self._by_player[pid] = game.id
        return game

    def get(self, game_id: int) -> Optional[Game]:
        return self._games.get(game_id)

    def for_player(self, chat_id: int) -> Optional[Game]:
        gid = self._by_player.get(chat_id)
        return self._games.get(gid) if gid is not None else None

    def is_busy(self, chat_id: int) -> bool:
        return chat_id in self._by_player

    def release_players(self, game: Game) -> None:
        """بعد از پایان بازی، بازیکن‌ها را آزاد می‌کند تا بتوانند بازی جدید شروع کنند."""
        for pid in game.human_players():
            if self._by_player.get(pid) == game.id:
                del self._by_player[pid]

    def remove(self, game_id: int) -> None:
        game = self._games.pop(game_id, None)
        if game:
            self.release_players(game)

    def active_games(self) -> List[Game]:
        return [g for g in self._games.values() if g.is_active]

    def finished_games(self) -> List[Game]:
        return [g for g in self._games.values() if not g.is_active]
