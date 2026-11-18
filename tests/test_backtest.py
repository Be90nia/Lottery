from lottery.backtest import rolling_origin_backtest, _probabilities
import pytest


def _draw(draw_id, front, back):
    return {"draw_id": str(draw_id), "draw_date": f"2020-01-{draw_id:02d}",
            "front_numbers": front, "back_numbers": back}


def test_uniform_probability_mass_matches_pick_count():
    rows = [_draw(1, [1, 2, 3, 4, 5], [1, 2]),
            _draw(2, [2, 3, 4, 5, 6], [2, 3])]
    for model in ("uniform", "expanding", "ewma"):
        front = _probabilities(rows, "front_numbers", 35, 5, model=model)
        back = _probabilities(rows, "back_numbers", 12, 2, model=model)
        assert sum(front) == pytest.approx(5)
        assert sum(back) == pytest.approx(2)


def test_backtest_is_strictly_time_ordered_and_reports_all_models():
    rows = [_draw(i, [1, 2, 3, 4, 5], [1, 2]) for i in range(1, 8)]
    result = rolling_origin_backtest(rows, min_train=3)
    assert result["evaluated_draws"] == 4
    assert result["first_evaluation_draw"] == "4"
    assert set(result["metrics"]) == {"uniform", "expanding", "ewma"}


def test_duplicate_draw_ids_rejected():
    rows = [_draw(1, [1, 2, 3, 4, 5], [1, 2]),
            _draw(1, [2, 3, 4, 5, 6], [2, 3])]
    with pytest.raises(ValueError, match="duplicate"):
        rolling_origin_backtest(rows, min_train=1)


def test_invalid_duplicate_numbers_rejected():
    rows = [_draw(1, [1, 1, 3, 4, 5], [1, 2]),
            _draw(2, [2, 3, 4, 5, 6], [2, 3])]
    with pytest.raises(ValueError, match="invalid front_numbers"):
        rolling_origin_backtest(rows, min_train=1)
