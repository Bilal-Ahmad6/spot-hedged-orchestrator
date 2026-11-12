import numpy as np
import pytest

from spothedge.forecast.seasonal import HistoryView, SeasonalNaiveForecaster


def test_history_view_refuses_to_reveal_the_future():
    values = [1.0, 2.0, 3.0, 4.0]
    view = HistoryView(values, limit=2)
    assert view[0] == 1.0
    assert view[1] == 2.0
    assert view[-1] == 2.0
    with pytest.raises(IndexError):
        _ = view[2]
    with pytest.raises(TypeError):
        _ = view[0:2]


def test_forecast_tracks_a_periodic_series():
    minutes = 3 * 1440
    index = np.arange(minutes)
    series = 70.0 + 30.0 * np.sin(2 * np.pi * index / 1440.0)
    forecaster = SeasonalNaiveForecaster(horizon_seconds=1800, step_seconds=300)
    view = HistoryView(series, limit=minutes)
    forecaster.update(view)
    forecast = forecaster.forecast(view)

    assert forecast.points[0].at_seconds == 0
    assert forecast.points[-1].at_seconds == 1800
    # One day back is an exact match for a pure daily cycle.
    assert forecast.points[0].vcpu == pytest.approx(series[minutes - 1], abs=1e-6)


def test_p90_is_never_below_the_point_forecast():
    series = np.full(2 * 1440, 50.0) + np.random.default_rng(3).normal(0, 5, 2 * 1440)
    forecaster = SeasonalNaiveForecaster()
    view = HistoryView(series, limit=2 * 1440)
    forecaster.update(view)
    forecast = forecaster.forecast(view)
    assert all(p.vcpu_p90 >= p.vcpu for p in forecast.points)


def test_short_history_is_flagged_as_degraded():
    series = np.full(120, 40.0)
    forecaster = SeasonalNaiveForecaster()
    view = HistoryView(series, limit=120)
    forecaster.update(view)
    assert forecaster.forecast(view).degraded is True
