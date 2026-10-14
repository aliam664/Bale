"""منطق بازی دوز (Tic-Tac-Toe) و هوش مصنوعی Minimax.

این ماژول هیچ وابستگی‌ای به بله ندارد و به‌تنهایی قابل تست است.
خانه‌ها با اندیس ۰ تا ۸ شماره‌گذاری می‌شوند:

    0 | 1 | 2
    3 | 4 | 5
    6 | 7 | 8
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional, Tuple

X = "X"
O = "O"
EMPTY = ""
DRAW = "draw"

LINES: Tuple[Tuple[int, int, int], ...] = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),   # ردیف‌ها
    (0, 3, 6), (1, 4, 7), (2, 5, 8),   # ستون‌ها
    (0, 4, 8), (2, 4, 6),              # قطرها
)

LEVELS = ("easy", "medium", "hard")


def other(player: str) -> str:
    return O if player == X else X


@dataclass
class Board:
    cells: List[str] = field(default_factory=lambda: [EMPTY] * 9)

    # ---------------------------------------------------------------- state
    def copy(self) -> "Board":
        return Board(self.cells[:])

    def legal_moves(self) -> List[int]:
        return [i for i, c in enumerate(self.cells) if c == EMPTY]

    def is_legal(self, idx: int) -> bool:
        return 0 <= idx < 9 and self.cells[idx] == EMPTY

    def play(self, idx: int, player: str) -> None:
        if player not in (X, O):
            raise ValueError(f"invalid player {player!r}")
        if not self.is_legal(idx):
            raise ValueError(f"illegal move {idx}")
        self.cells[idx] = player

    def winning_line(self) -> Optional[Tuple[int, int, int]]:
        for a, b, c in LINES:
            if self.cells[a] and self.cells[a] == self.cells[b] == self.cells[c]:
                return (a, b, c)
        return None

    def winner(self) -> Optional[str]:
        line = self.winning_line()
        return self.cells[line[0]] if line else None

    def is_full(self) -> bool:
        return all(self.cells)

    def result(self) -> Optional[str]:
        """``"X"`` / ``"O"`` / ``"draw"`` یا ``None`` اگر بازی ادامه دارد."""
        w = self.winner()
        if w:
            return w
        if self.is_full():
            return DRAW
        return None

    def is_over(self) -> bool:
        return self.result() is not None

    def key(self) -> Tuple[str, ...]:
        return tuple(self.cells)


# ------------------------------------------------------------------ minimax
@lru_cache(maxsize=None)
def _minimax(cells: Tuple[str, ...], to_move: str, me: str) -> int:
    """امتیاز موقعیت از دید بازیکن ``me``؛ مثبت = برد، منفی = باخت، صفر = مساوی.
    قدر مطلق امتیاز با سرعت رسیدن به نتیجه زیاد می‌شود تا بردِ سریع‌تر/باختِ دیرتر ترجیح داده شود."""
    board = Board(list(cells))
    res = board.result()
    empties = len(board.legal_moves())
    if res == me:
        return 1 + empties
    if res == DRAW:
        return 0
    if res is not None:          # حریف برده
        return -(1 + empties)

    scores = []
    for idx in board.legal_moves():
        nxt = board.copy()
        nxt.play(idx, to_move)
        scores.append(_minimax(nxt.key(), other(to_move), me))
    return max(scores) if to_move == me else min(scores)


def best_move(board: Board, player: str, rng: Optional[random.Random] = None) -> int:
    """بهترین حرکت برای ``player`` (بین حرکت‌های هم‌امتیاز، تصادفی انتخاب می‌کند)."""
    rng = rng or random
    moves = board.legal_moves()
    if not moves:
        raise ValueError("no legal moves")
    scored = []
    for idx in moves:
        nxt = board.copy()
        nxt.play(idx, player)
        scored.append((_minimax(nxt.key(), other(player), player), idx))
    top = max(s for s, _ in scored)
    return rng.choice([idx for s, idx in scored if s == top])


def choose_move(board: Board, player: str, level: str = "hard",
                rng: Optional[random.Random] = None) -> int:
    """انتخاب حرکت کامپیوتر بر اساس سطح دشواری.

    easy   : کاملاً تصادفی
    medium : نیمی از مواقع بهینه، نیمی تصادفی
    hard   : همیشه بهینه (شکست‌ناپذیر)
    """
    rng = rng or random
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}")
    if level == "easy" or (level == "medium" and rng.random() < 0.5):
        return rng.choice(board.legal_moves())
    return best_move(board, player, rng)
