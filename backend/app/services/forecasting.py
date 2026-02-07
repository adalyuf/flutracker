from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import curve_fit
from scipy.stats import norm

from backend.app.schemas import ForecastPoint


def _gaussian(x, amplitude, mean, sigma):
    """Gaussian function for curve fitting flu season shape."""
    return amplitude * np.exp(-((x - mean) ** 2) / (2 * sigma ** 2))


def generate_forecast(
    dates: list[datetime],
    values: list[int],
    weeks_ahead: int = 4,
) -> tuple[list[ForecastPoint], str | None, float | None]:
    """
    Fit a Gaussian curve to the current season's flu data and project forward.
    Returns (forecast_points, peak_date, peak_magnitude).
    """
    if len(values) < 4:
        return [], None, None

    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)

    # Initial parameter guesses
    amp_guess = float(np.max(y))
    mean_guess = float(np.argmax(y))
    sigma_guess = max(float(len(y) / 4), 1.0)

    try:
        popt, pcov = curve_fit(
            _gaussian, x, y,
            p0=[amp_guess, mean_guess, sigma_guess],
            maxfev=5000,
            bounds=([0, -len(y), 0.5], [amp_guess * 5, len(y) * 2, len(y) * 2]),
        )
    except (RuntimeError, ValueError):
        # Fallback: linear extrapolation from last 4 weeks
        return _linear_fallback(dates, values, weeks_ahead)

    amplitude, mean, sigma = popt
    perr = np.sqrt(np.diag(pcov)) if pcov is not None else np.array([0, 0, 0])

    forecast_points = []
    last_date = dates[-1] if dates else datetime.utcnow()

    for i in range(1, weeks_ahead + 1):
        x_future = len(values) - 1 + i
        predicted = max(0, float(_gaussian(x_future, *popt)))

        # Uncertainty grows with distance from data
        uncertainty_factor = 1 + (i * 0.3)
        residuals = y - _gaussian(x, *popt)
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        se = rmse * uncertainty_factor

        forecast_date = last_date + timedelta(weeks=i)
        forecast_points.append(ForecastPoint(
            date=forecast_date.strftime("%Y-%m-%d"),
            predicted_cases=round(predicted),
            lower_80=round(max(0, predicted - 1.28 * se)),
            upper_80=round(predicted + 1.28 * se),
            lower_95=round(max(0, predicted - 1.96 * se)),
            upper_95=round(predicted + 1.96 * se),
        ))

    # Peak calculation
    peak_x = mean
    peak_date_dt = dates[0] + timedelta(weeks=peak_x) if dates else None
    peak_date = peak_date_dt.strftime("%Y-%m-%d") if peak_date_dt else None
    peak_magnitude = round(float(amplitude))

    return forecast_points, peak_date, peak_magnitude


def _linear_fallback(
    dates: list[datetime],
    values: list[int],
    weeks_ahead: int,
) -> tuple[list[ForecastPoint], str | None, float | None]:
    """Simple linear extrapolation when curve fitting fails."""
    recent = values[-4:] if len(values) >= 4 else values
    x = np.arange(len(recent), dtype=float)
    y = np.array(recent, dtype=float)

    if len(x) < 2:
        return [], None, None

    slope = float(np.polyfit(x, y, 1)[0])
    last_val = float(y[-1])
    last_date = dates[-1]
    std = float(np.std(y)) if len(y) > 1 else last_val * 0.2

    points = []
    for i in range(1, weeks_ahead + 1):
        predicted = max(0, last_val + slope * i)
        se = std * (1 + i * 0.3)
        forecast_date = last_date + timedelta(weeks=i)
        points.append(ForecastPoint(
            date=forecast_date.strftime("%Y-%m-%d"),
            predicted_cases=round(predicted),
            lower_80=round(max(0, predicted - 1.28 * se)),
            upper_80=round(predicted + 1.28 * se),
            lower_95=round(max(0, predicted - 1.96 * se)),
            upper_95=round(predicted + 1.96 * se),
        ))

    return points, None, None
