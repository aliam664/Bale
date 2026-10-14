import random

import pytest

from bot.tictactoe import DRAW, EMPTY, O, X, Board, best_move, choose_move, other


def make(cells: str) -> Board:
    """ساخت تخته از رشتهٔ ۹ کاراکتری؛ '.' = خالی."""
    assert len(cells) == 9
    return Board([EMPTY if c == "." else c for c in cells])


def test_empty_board():
    b = Board()
    assert b.legal_moves() == list(range(9))
    assert b.result() is None and not b.is_over()


@pytest.mark.parametrize("cells, winner", [
    ("XXX......", X), ("...OOO...", O), ("......XXX", X),
    ("X..X..X..", X), (".O..O..O.", O), ("..X..X..X", X),
    ("X...X...X", X), ("..O.O.O..", O),
])
def test_winning_lines(cells, winner):
    b = make(cells)
    assert b.winner() == winner
    assert b.result() == winner
    assert b.winning_line() is not None


def test_draw():
    b = make("XOXXOOOXX")
    assert b.winner() is None
    assert b.is_full()
    assert b.result() == DRAW


def test_illegal_moves():
    b = make("X........")
    with pytest.raises(ValueError):
        b.play(0, O)          # خانهٔ پر
    with pytest.raises(ValueError):
        b.play(9, O)          # خارج از تخته
    with pytest.raises(ValueError):
        b.play(1, "Z")        # بازیکن نامعتبر


def test_best_move_takes_win():
    # X می‌تواند با خانهٔ ۲ ببرد.
    assert best_move(make("XX..O.O.."), X) == 2


def test_best_move_blocks_loss():
    # O باید خانهٔ ۲ را ببندد.
    assert best_move(make("XX...O..."), O) == 2


def test_best_move_prefers_fast_win():
    # X با خانهٔ ۲ فوراً می‌برد؛ نباید حرکت کندتر انتخاب کند.
    rng = random.Random(0)
    for _ in range(20):
        assert best_move(make("XX.OO...."), X, rng) == 2


def _all_outcomes_vs_minimax(board: Board, to_move: str, ai: str, rng: random.Random, results: set) -> None:
    """همهٔ شاخه‌های ممکن حرکت حریف را می‌پیماید؛ AI همیشه بهینه بازی می‌کند."""
    res = board.result()
    if res is not None:
        results.add(res)
        return
    if to_move == ai:
        nxt = board.copy()
        nxt.play(best_move(board, ai, rng), ai)
        _all_outcomes_vs_minimax(nxt, other(ai), ai, rng, results)
    else:
        for idx in board.legal_moves():
            nxt = board.copy()
            nxt.play(idx, to_move)
            _all_outcomes_vs_minimax(nxt, other(to_move), ai, rng, results)


@pytest.mark.parametrize("ai", [X, O])
def test_minimax_never_loses(ai):
    results: set = set()
    _all_outcomes_vs_minimax(Board(), X, ai, random.Random(1), results)
    assert other(ai) not in results, f"AI as {ai} lost in some line: {results}"
    assert results <= {ai, DRAW}


def test_choose_move_levels_return_legal_moves():
    rng = random.Random(42)
    for level in ("easy", "medium", "hard"):
        for _ in range(30):
            b = Board()
            player = X
            while not b.is_over():
                idx = choose_move(b, player, level, rng)
                assert b.is_legal(idx)
                b.play(idx, player)
                player = other(player)


def test_choose_move_unknown_level():
    with pytest.raises(ValueError):
        choose_move(Board(), X, "impossible")
