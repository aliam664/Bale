"""ساخت صفحه‌کلیدهای شیشه‌ای (InlineKeyboardMarkup) طبق مستندات بله.

قرارداد callback_data (حداکثر ۶۴ بایت):
    menu:human | menu:cpu | menu:help | menu:home
    cpu:<easy|medium|hard>
    q:cancel
    mv:<game_id>:<0..8>
    g:resign:<game_id> | g:again:<game_id>
    noop
"""
from __future__ import annotations

from typing import Dict, List

from .texts import LEVEL_NAMES, SYMBOLS
from .tictactoe import Board


def button(text: str, data: str) -> Dict[str, str]:
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data too long: {data!r}")
    return {"text": text, "callback_data": data}


def markup(rows: List[List[Dict[str, str]]]) -> Dict[str, list]:
    return {"inline_keyboard": rows}


def main_menu() -> Dict[str, list]:
    return markup([
        [button("🎮 بازی با حریف آنلاین", "menu:human")],
        [button("🤖 بازی با کامپیوتر", "menu:cpu")],
        [button("❓ راهنما", "menu:help")],
    ])


def back_to_menu() -> Dict[str, list]:
    return markup([[button("🏠 منوی اصلی", "menu:home")]])


def waiting() -> Dict[str, list]:
    return markup([[button("❌ انصراف", "q:cancel")]])


def queue_timeout() -> Dict[str, list]:
    return markup([
        [button("🔄 تلاش دوباره", "menu:human")],
        [button("🤖 بازی با کامپیوتر", "menu:cpu")],
    ])


def cpu_levels() -> Dict[str, list]:
    return markup([
        [button(f"🙂 {LEVEL_NAMES['easy']}", "cpu:easy"),
         button(f"😐 {LEVEL_NAMES['medium']}", "cpu:medium"),
         button(f"😈 {LEVEL_NAMES['hard']}", "cpu:hard")],
        [button("🏠 منوی اصلی", "menu:home")],
    ])


def board_rows(board: Board, game_id: int, active: bool) -> List[List[Dict[str, str]]]:
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            data = f"mv:{game_id}:{idx}" if active else "noop"
            row.append(button(SYMBOLS[board.cells[idx]], data))
        rows.append(row)
    return rows


def game_board(board: Board, game_id: int) -> Dict[str, list]:
    rows = board_rows(board, game_id, active=True)
    rows.append([button("🏳️ تسلیم", f"g:resign:{game_id}")])
    return markup(rows)


def finished_board(board: Board, game_id: int, allow_rematch: bool = True) -> Dict[str, list]:
    rows = board_rows(board, game_id, active=False)
    last = []
    if allow_rematch:
        last.append(button("🔁 بازی مجدد", f"g:again:{game_id}"))
    last.append(button("🏠 منوی اصلی", "menu:home"))
    rows.append(last)
    return markup(rows)
