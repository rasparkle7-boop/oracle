"""Asian / European handicap settlement and fair-odds maths.

Quarter lines split the stake across adjacent half/whole lines. Push is a
refund, not a loss. These helpers are used by the market engine and the slip
calculator; they do not depend on bookmaker prices.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def is_quarter(line: float) -> bool:
    return abs((float(line) * 4) - round(float(line) * 4)) < 1e-9 and abs((float(line) * 2) - round(float(line) * 2)) > 1e-9


def _component(margin: int, line: float) -> str:
    adjusted = margin + line
    if adjusted > 0:
        return "win"
    if adjusted == 0:
        return "push"
    return "loss"


def settlement_from_margin(margin_values: np.ndarray, margin_probs: np.ndarray,
                           line: float) -> dict[str, float]:
    line = float(line)
    out = {"win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 0.0}
    for margin, prob in zip(margin_values.tolist(), margin_probs.tolist()):
        margin = int(round(margin))
        if is_quarter(line):
            a = _component(margin, line - 0.25)
            b = _component(margin, line + 0.25)
            if a == "win" and b == "win":
                out["win"] += prob
            elif a == "win" and b == "push" or a == "push" and b == "win":
                out["half_win"] += prob
            elif a == "push" and b == "loss" or a == "loss" and b == "push":
                out["half_loss"] += prob
            elif a == "loss" and b == "loss":
                out["loss"] += prob
            elif a == "push" and b == "push":
                out["push"] += prob
            else:
                # one half wins, the other loses: impossible for adjacent quarter
                # lines unless margin is exactly on a boundary; treat as push.
                out["push"] += prob
        else:
            result = _component(margin, line)
            out[result] += prob
    return {k: round(v, 6) for k, v in out.items()}


def fair_decimal(settlement: dict[str, float]) -> float:
    p_win = settlement.get("win", 0.0)
    p_half_win = settlement.get("half_win", 0.0)
    p_half_loss = settlement.get("half_loss", 0.0)
    p_loss = settlement.get("loss", 0.0)
    numerator = p_loss + 0.5 * p_half_loss
    denominator = p_win + 0.5 * p_half_win
    if denominator <= 0:
        return 0.0
    return round(1.0 + numerator / denominator, 4)


def effective_probability(settlement: dict[str, float]) -> float:
    """Probability of a positive or refunded outcome, used for ranking only."""
    return round(settlement.get("win", 0.0) + 0.5 * settlement.get("half_win", 0.0)
                 + 0.5 * settlement.get("push", 0.0), 6)


def european_handicap(grid: np.ndarray, line: float) -> dict[str, float]:
    """Three-way result after applying a European handicap to the home side."""
    n = grid.shape[0]
    idx = np.arange(n)
    diff = np.subtract.outer(idx, idx)
    adjusted = diff + float(line)
    return {"home": float(grid[adjusted > 0].sum()),
            "draw": float(grid[adjusted == 0].sum()),
            "away": float(grid[adjusted < 0].sum())}
