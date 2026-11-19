"""Mode survival at entered sections, with a shared difficulty slope and section effects."""

from collections import defaultdict
from dataclasses import dataclass
from math import log, sqrt

import numpy as np

MODES = ("cube", "ship", "ball", "ufo", "wave", "robot", "spider", "swing")
TICK_HZ = 240
REFERENCE_SECONDS = 10
REFERENCE_LOG_HAZARD = log(log(2) / REFERENCE_SECONDS)


@dataclass(frozen=True)
class Section:
    mode: str
    generation: int
    level: str
    section: int
    speed: float
    mini: bool
    dual: bool
    start: str
    attempt: int
    ticks: int
    died: bool
    zero_shot: bool
    cleared: bool = False
    run: str = ""
    seed: int | None = None
    practice: bool = False

    @classmethod
    def from_row(cls, row):
        section = cls(
            row["mode"].lower(), row["generation"], row["level"], row["section"],
            row["speed"], row["mini"], row["dual"], row["start"], row["attempt"],
            row["ticks_in_section"], row["died"], row.get("zero_shot", False), row.get("cleared", False),
            row.get("run", ""), row.get("seed"), row.get("practice", False),
        )
        if section.mode not in MODES or section.start not in ("zero", "checkpoint", "startpos"):
            raise ValueError("unknown mode or reset kind")
        for value, minimum in ((section.generation, 0), (section.section, 0),
                               (section.attempt, 1), (section.ticks, 1)):
            if type(value) is not int or value < minimum:
                raise ValueError("invalid section counter")
        if not all(type(value) is bool for value in (
            section.mini, section.dual, section.died, section.zero_shot, section.cleared, section.practice,
        )):
            raise ValueError("section flags must be booleans")
        if section.cleared and section.died:
            raise ValueError("a death cannot also clear a section")
        if section.zero_shot and (section.start != "zero" or section.attempt != 1 or section.practice):
            raise ValueError("zero-shot evidence requires the first attempt from zero")
        return section

    @property
    def difficulty_key(self):
        return self.level, self.section, self.mode, self.speed, self.mini, self.dual


@dataclass(frozen=True)
class Anchor:
    score: float
    label: str
    gddl: bool = False


def evidence(rows):
    seconds = sum(row.ticks for row in rows) / TICK_HZ
    deaths = sum(row.died for row in rows)
    return {
        "seconds": round(seconds, 3), "entries": len(rows), "deaths": deaths,
        "deaths_per_minute": round(60 * deaths / seconds, 3) if seconds else None,
        "confirmed_exits": sum(row.cleared for row in rows),
        "checkpoint_entries": sum(row.start == "checkpoint" for row in rows),
        "startpos_entries": sum(row.start == "startpos" for row in rows),
    }


def posterior(rows, anchors):
    """Fit log hazard = -skill + slope * anchor + section offset.

    A Gaussian penalty shrinks the section offset toward zero. Fit the slope
    jointly with the mode/generation effects and solve via the Schur complement.
    """
    indexed = [(row, anchors[row.level]) for row in rows if row.level in anchors]
    keys = sorted({(row.mode, row.generation) for row, _ in indexed})
    if not keys:
        return {}, None
    groups = {key: i for i, key in enumerate(keys)}
    sections = {key: i for i, key in enumerate(dict.fromkeys(row.difficulty_key for row, _ in indexed))}
    x = np.zeros((len(indexed), len(keys) + 1))
    section_ids = np.empty(len(indexed), dtype=np.intp)
    exposures = np.empty(len(indexed))
    deaths = np.empty(len(indexed))
    for i, (row, anchor) in enumerate(indexed):
        x[i, groups[row.mode, row.generation]] = -1.0
        x[i, -1] = anchor.score
        section_ids[i] = sections[row.difficulty_key]
        exposures[i] = row.ticks / TICK_HZ
        deaths[i] = row.died

    center = np.array([-REFERENCE_LOG_HAZARD] * len(keys) + [0.55])
    precision = np.array([1 / 4**2] * len(keys) + [1 / 0.4**2])
    section_precision = 1 / 0.85**2
    beta = center.copy()
    effects = np.zeros(len(sections))

    def evaluate(global_coef, section_coef):
        eta = x @ global_coef + section_coef[section_ids]
        expected = np.exp(np.clip(eta, -700, 700)) * exposures
        penalty = precision @ (global_coef - center)**2 + section_precision * (section_coef @ section_coef)
        return expected.sum() - deaths @ eta + 0.5 * penalty, expected

    def information(weight):
        section_h = np.bincount(section_ids, weights=weight, minlength=len(sections)) + section_precision
        cross = np.zeros((len(keys) + 1, len(sections)))
        np.add.at(cross.T, section_ids, x * weight[:, None])
        reduced = (x.T * weight) @ x + np.diag(precision) - (cross / section_h) @ cross.T
        return reduced, cross, section_h

    for _ in range(60):
        value, expected = evaluate(beta, effects)
        residual = expected - deaths
        grad = x.T @ residual + precision * (beta - center)
        section_grad = np.bincount(section_ids, weights=residual, minlength=len(sections)) + section_precision * effects
        reduced, cross, section_h = information(expected)
        rhs = -grad + cross @ (section_grad / section_h)
        step = np.linalg.solve(reduced, rhs)
        # The fit uses an increasing difficulty scale. Solve the active bound
        # jointly with the other coefficients instead of clipping them afterward.
        if beta[-1] + step[-1] < 0.05:
            step[-1] = 0.05 - beta[-1]
            step[:-1] = np.linalg.solve(reduced[:-1, :-1], rhs[:-1] - reduced[:-1, -1] * step[-1])
        section_step = (-section_grad - cross.T @ step) / section_h
        if max(np.max(np.abs(step)), np.max(np.abs(section_step))) < 1e-7:
            break
        for attempt in range(24):
            fraction = 0.5**attempt
            trial_beta = beta + fraction * step
            trial_effects = effects + fraction * section_step
            if evaluate(trial_beta, trial_effects)[0] <= value:
                beta, effects = trial_beta, trial_effects
                break
        else:
            break

    covariance = np.linalg.inv(information(evaluate(beta, effects)[1])[0])
    estimates = {}
    for key, i in groups.items():
        slope = beta[-1]
        rating = (beta[i] + REFERENCE_LOG_HAZARD) / slope
        gradient = np.zeros(len(beta))
        gradient[i], gradient[-1] = 1 / slope, -rating / slope
        rating_margin = 1.96 * sqrt(max(0, gradient @ covariance @ gradient))
        theta_margin = 1.96 * sqrt(covariance[i, i])
        estimates[key] = {
            "theta": float(beta[i]), "theta_interval": [beta[i] - theta_margin, beta[i] + theta_margin],
            "rating": float(rating), "interval": [rating - rating_margin, rating + rating_margin],
        }
    return estimates, float(beta[-1])


def summarize(rows, anchors):
    result = {}
    scopes = {
        "zero_shot": [row for row in rows if row.zero_shot],
        "full": [row for row in rows if row.start == "zero" and not row.practice],
        "all": rows,
    }
    for scope, relevant in scopes.items():
        by_group = defaultdict(list)
        for row in relevant:
            by_group[row.mode, row.generation].append(row)
        fit, slope = posterior(relevant, anchors)
        trends = []
        for (mode, generation), group in sorted(by_group.items(), key=lambda item: (item[0][1], MODES.index(item[0][0]))):
            known = [row for row in group if row.level in anchors]
            gddl = [row for row in known if anchors[row.level].gddl]
            estimate = fit.get((mode, generation))
            ref_values = [anchors[row.level].score for row in known]
            calibration = None
            if (
                estimate and evidence(known)["seconds"] >= REFERENCE_SECONDS
                and len({row.level for row in known}) >= 2 and any(row.died for row in known)
                and min(ref_values) <= estimate["rating"] <= max(ref_values)
            ):
                if estimate["rating"] < 1:
                    calibration = "pre_demon"
                elif len({anchors[row.level].score for row in gddl}) >= 2 and estimate["rating"] >= min(
                    anchors[row.level].score for row in gddl
                ):
                    calibration = "gddl"
            levels = []
            for level in sorted({row.level for row in group}):
                level_rows = [row for row in group if row.level == level]
                anchor = anchors.get(level)
                first_exits = {}
                for row in level_rows:
                    if row.cleared:
                        key = row.run, row.seed, row.practice, row.difficulty_key
                        previous = first_exits.get(key)
                        first_exits[key] = row.attempt if previous is None else min(previous, row.attempt)
                levels.append({"level": level, "anchor": anchor.label if anchor else None,
                               "mean_attempts_to_first_section_clear": (
                                   sum(first_exits.values()) / len(first_exits) if first_exits else None
                               ),
                               **evidence(level_rows)})
            trends.append({
                "mode": mode, "generation": generation, **evidence(group),
                "anchored_seconds": evidence(known)["seconds"], "calibration": calibration,
                "rating": estimate["rating"] if calibration else None,
                "interval": estimate["interval"] if calibration else None,
                "levels": levels,
            })
        result[scope] = {"trend": trends, "difficulty_slope": slope}
    return result
