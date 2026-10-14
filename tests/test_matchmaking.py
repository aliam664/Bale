import pytest

from bot.matchmaking import (CPU, REASON_DRAW, REASON_RESIGN, REASON_WIN, STATUS_FINISHED,
                             GameManager, Matchmaker)
from bot.tictactoe import O, X


def test_queue_pairs_first_two_players():
    mm = Matchmaker()
    assert mm.join(1, now=0) is None
    assert mm.in_queue(1) and len(mm) == 1
    assert mm.join(1, now=1) is None          # ورود دوباره بی‌اثر است
    assert mm.join(2, now=2) == (1, 2)        # نفر اول حریف نفر دوم می‌شود
    assert len(mm) == 0
    assert not mm.in_queue(1) and not mm.in_queue(2)


def test_queue_leave_and_expiry():
    mm = Matchmaker()
    mm.join(1, now=0)
    assert mm.leave(1) is True
    assert mm.leave(1) is False
    mm.join(2, now=10)
    mm.join(3, now=10)              # 2 و 3 جفت می‌شوند؛ صف خالی
    mm.join(4, now=20)
    assert mm.pop_expired(now=25, max_wait=10) == []
    assert mm.pop_expired(now=30, max_wait=10) == [4]
    assert len(mm) == 0


def test_game_manager_mapping_and_release():
    gm = GameManager()
    g = gm.create(10, 20, now=0)
    assert g.id == 1
    assert g.players == {X: 10, O: 20}
    assert gm.for_player(10) is g and gm.for_player(20) is g
    assert gm.is_busy(10)
    assert g.symbol_of(10) == X and g.symbol_of(20) == O and g.symbol_of(99) is None
    assert g.opponent_of(10) == 20

    g.finish(winner_symbol=O, reason=REASON_RESIGN, now=5)
    assert g.status == STATUS_FINISHED and g.result == O
    gm.release_players(g)
    assert gm.for_player(10) is None and not gm.is_busy(20)
    assert gm.finished_games() == [g] and gm.active_games() == []


def test_cpu_game_properties():
    gm = GameManager()
    g = gm.create(CPU, 7, cpu_level="hard", now=0)
    assert g.is_cpu_game
    assert g.human_players() == [7]
    assert g.current_player == CPU
    assert gm.for_player(7) is g


def test_apply_move_rules_and_win():
    gm = GameManager()
    g = gm.create(1, 2, now=0)
    with pytest.raises(ValueError):
        g.apply_move(2, 0, now=1)         # نوبت X (بازیکن 1) است
    g.apply_move(1, 0, now=1)
    assert g.turn == O and g.move_count == 1
    with pytest.raises(ValueError):
        g.apply_move(2, 0, now=2)         # خانهٔ پر
    g.apply_move(2, 3, now=2)
    g.apply_move(1, 1, now=3)
    g.apply_move(2, 4, now=4)
    g.apply_move(1, 2, now=5)             # X: 0,1,2 → برد
    assert not g.is_active and g.result == X and g.end_reason == REASON_WIN
    with pytest.raises(ValueError):
        g.apply_move(2, 5, now=6)         # بازی تمام شده


def test_apply_move_draw():
    gm = GameManager()
    g = gm.create(1, 2, now=0)
    # X O X / X O O / O X X  → مساوی
    seq = [(1, 0), (2, 1), (1, 2), (2, 4), (1, 3), (2, 5), (1, 7), (2, 6), (1, 8)]
    for i, (p, idx) in enumerate(seq):
        g.apply_move(p, idx, now=i)
    assert g.result == "draw" and g.end_reason == REASON_DRAW
