"""Grade distribution plots.

Optional: needs the ``plot`` extra.

The look is deliberately plain and technical - monospace type, an outlined histogram,
and the observed distribution drawn against a fitted normal so you can see at a glance
how far the class departs from it. An optional second panel breaks the same data down
by criterion, which is usually what tells you the rubric needs adjusting.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from canvasgrade.workflow import PreparedSheet

STYLE = {
    "font.family": "monospace",
    "font.size": 12,
    "axes.titlesize": 15,
    "axes.labelsize": 13,
    "legend.fontsize": 11,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
}

#: Matplotlib 3.11 deprecated ``vert=False`` in favour of ``orientation``; support both
#: so the plot extra keeps working across the versions people actually have installed.
_HORIZONTAL: dict[str, object] = (
    {"orientation": "horizontal"}
    if tuple(int(part) for part in matplotlib.__version__.split(".")[:2]) >= (3, 11)
    else {"vert": False}
)

NORMAL_COLOR = "#1F4EA1"
KDE_COLOR = "#D62728"
#: Headroom above the tallest bar, leaving room for the stats block and the legend.
HEADROOM = 1.38


def _totals(prepared: PreparedSheet) -> np.ndarray:
    """Total per student: the sheet's own total column when it has one, else the sum."""
    values = []
    for row in prepared.rows:
        if row.total_override is not None:
            values.append(row.total_override)
        elif row.scores:
            values.append(sum(score for _, score in row.scores))
    return np.asarray(values, dtype=float)


def _criterion_series(prepared: PreparedSheet) -> list[tuple[str, float, np.ndarray]]:
    from canvasgrade.sheet.detect import strip_points

    series = []
    for column in prepared.mapping.criteria_columns:
        scores = [row.score_map[column.name] for row in prepared.rows if column.name in row.score_map]
        if scores:
            series.append((strip_points(column.name), float(column.points or max(scores)), np.asarray(scores)))
    return series


def _stats_block(scores: np.ndarray) -> str:
    """Right-aligned monospace summary, in the order a marker reads them."""
    return (
        f"   n: {len(scores)}\n"
        f"  Q1: {np.quantile(scores, 0.25):.3f}\n"
        f"  Q2: {np.quantile(scores, 0.5):.3f}\n"
        f"  Q3: {np.quantile(scores, 0.75):.3f}\n"
        f"Mean: {np.mean(scores):.3f}\n"
        f" Std: {np.std(scores):.3f}"
    )


def _draw_totals(axis: plt.Axes, scores: np.ndarray, *, xmin: float, xmax: float, bins: int) -> None:
    edges = np.linspace(xmin, xmax, bins + 1)
    counts, _ = np.histogram(scores, bins=edges)
    ymax = max(float(counts.max()), 1.0)
    grid = np.linspace(xmin, xmax, 1000)
    #: Scale densities from probability to expected counts per bin.
    scale = len(scores) * (xmax - xmin) / bins

    axis.hist(scores, bins=edges, fill=False, edgecolor="black", linewidth=1.1)

    std = float(np.std(scores))
    if std > 0:
        from scipy.stats import norm

        axis.plot(
            grid,
            norm(float(np.mean(scores)), std).pdf(grid) * scale,
            color=NORMAL_COLOR,
            linewidth=1.4,
            label="Normal Distribution",
        )
    if len(scores) > 1 and std > 0:
        from scipy.stats import gaussian_kde

        axis.plot(
            grid,
            gaussian_kde(scores).evaluate(grid) * scale,
            color=KDE_COLOR,
            linewidth=1.4,
            dashes=[2, 2],
            label="Estimated Distribution",
        )

    axis.text(
        0.03,
        0.97,
        _stats_block(scores),
        transform=axis.transAxes,
        va="top",
        ha="left",
        family="monospace",
    )

    axis.set_xlim(xmin, xmax)
    axis.set_ylim(0, ymax * HEADROOM)
    axis.set_yticks(_integer_ticks(ymax))
    axis.set_xlabel("Score")
    axis.set_ylabel("Frequency")
    if std > 0:
        axis.legend(loc="upper right", framealpha=1.0, edgecolor="#BBBBBB")


def _draw_box(axis: plt.Axes, scores: np.ndarray, *, xmin: float, xmax: float) -> None:
    """The box plot lives in its own slim panel above the histogram, sharing its x scale.

    Floating it inside the histogram, as the classic layout did, means it eventually
    collides with the legend or the stats block on some data set. This cannot.
    """
    axis.boxplot(
        scores,
        widths=0.5,
        positions=[0],
        manage_ticks=False,
        medianprops={"color": KDE_COLOR, "linewidth": 1.4},
        flierprops={"marker": "o", "markersize": 4, "markerfacecolor": "none", "markeredgecolor": "black"},
        **_HORIZONTAL,
    )
    axis.set_xlim(xmin, xmax)
    axis.set_ylim(-0.55, 0.55)
    axis.set_xticks([])
    axis.set_yticks([])
    for spine in axis.spines.values():
        spine.set_visible(False)


def _integer_ticks(ymax: float, target: int = 6) -> np.ndarray:
    """Whole-number frequency ticks, since fractional students do not exist."""
    step = max(1, int(np.ceil(ymax / target)))
    return np.arange(0, int(ymax) + step, step)


def _draw_criteria(axis: plt.Axes, series: list[tuple[str, float, np.ndarray]]) -> None:
    """One bar per criterion: mean score as a fraction of the maximum."""
    fractions = [float(np.mean(scores)) / maximum if maximum else 0.0 for _, maximum, scores in series]
    positions = np.arange(len(series))

    axis.barh(positions, fractions, color="white", edgecolor="black", linewidth=1.1, height=0.62)
    for position, fraction, (_, maximum, scores) in zip(positions, fractions, series, strict=True):
        axis.text(
            fraction + 0.015,
            position,
            f"{np.mean(scores):.2f}/{maximum:g}",
            va="center",
            fontsize=10,
        )

    axis.set_yticks(positions, [name for name, _, _ in series], fontsize=11)
    axis.invert_yaxis()
    axis.set_xlim(0, 1.18)
    axis.set_xticks(np.linspace(0, 1, 6))
    axis.axvline(1.0, color=NORMAL_COLOR, linewidth=1.0, dashes=[3, 3])
    axis.set_xlabel("Mean score / maximum")
    axis.set_title("By criterion", fontsize=13, pad=8)


def plot_sheet(
    prepared: PreparedSheet,
    *,
    output: Path,
    title: str = "Grades Plot",
    xmin: float = 0.0,
    xmax: float | None = None,
    bins: int = 20,
    by_criterion: bool = False,
    dpi: int = 200,
) -> Path:
    """Render the distribution for a prepared sheet and save it."""
    scores = _totals(prepared)
    if scores.size == 0:
        raise ValueError("No totals to plot: the sheet has no scores and no total column.")

    if xmax is None:
        declared = sum(column.points or 0 for column in prepared.mapping.criteria_columns)
        xmax = float(declared) if declared > 0 else float(np.max(scores))
    xmax = max(xmax, float(np.max(scores)))
    if xmax <= xmin:
        raise ValueError(f"xmax ({xmax:g}) must be greater than xmin ({xmin:g})")

    series = _criterion_series(prepared) if by_criterion else []

    with plt.rc_context(STYLE):
        ratios = [0.32, 4.2] + ([max(1.4, len(series) * 0.42)] if series else [])
        height = 7.0 + (0.34 * len(series) if series else 0)
        figure, axes = plt.subplots(
            len(ratios),
            1,
            figsize=(9.5, height),
            dpi=dpi,
            gridspec_kw={"height_ratios": ratios},
            layout="constrained",
        )

        _draw_box(axes[0], scores, xmin=xmin, xmax=xmax)
        _draw_totals(axes[1], scores, xmin=xmin, xmax=xmax, bins=bins)
        if series:
            _draw_criteria(axes[2], series)

        figure.suptitle(title, fontsize=16)
        figure.savefig(output, dpi=dpi, bbox_inches="tight")
        plt.close(figure)
    return output
