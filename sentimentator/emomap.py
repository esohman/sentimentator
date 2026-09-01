# -*- coding: utf-8 -*-
"""Pure EmoMap geometry and scheduling utilities.

This module has no Flask or SQLAlchemy dependency, which makes the core
experimental logic easy to unit-test independently of the web application.
"""

from collections import defaultdict
import hashlib
import json
import math
import random

SCHEME_VERSION = "emomap-wheel-v3"
WHEEL_VERSION = "ohman-inverted-plutchik-960x720-v1"

WHEEL_WIDTH = 960.0
WHEEL_HEIGHT = 720.0
WHEEL_CENTER_X = 480.0
WHEEL_CENTER_Y = 368.0
WHEEL_MAX_RADIUS = 320.0
MAX_WHEEL_POINTS = 8
VALID_COARSE = {"pos", "neg", "neither", "both"}


def geometry(x_norm, y_norm):
    """Convert normalized click coordinates to canonical EmoMap geometry."""
    x = float(x_norm)
    y = float(y_norm)
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError("Wheel coordinates must be in [0,1].")

    canonical_x = x * WHEEL_WIDTH
    canonical_y = y * WHEEL_HEIGHT
    dx = canonical_x - WHEEL_CENTER_X
    dy = WHEEL_CENTER_Y - canonical_y  # positive y points upward
    radius = math.hypot(dx, dy) / WHEEL_MAX_RADIUS
    angle = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0

    return {
        "x_norm": round(x, 6),
        "y_norm": round(y, 6),
        "canonical_x": round(canonical_x, 3),
        "canonical_y": round(canonical_y, 3),
        "dx": round(dx, 3),
        "dy": round(dy, 3),
        "radius": round(radius, 6),
        "angle_deg": round(angle, 3),
    }


def parse_points(raw):
    """Validate a browser wheel-points payload and return derived geometry."""
    try:
        points = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid wheel-points JSON.") from exc

    if not isinstance(points, list) or not (1 <= len(points) <= MAX_WHEEL_POINTS):
        raise ValueError(f"Select between 1 and {MAX_WHEEL_POINTS} wheel points.")

    clean = []
    for point in points:
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            raise ValueError("Each wheel point requires x and y.")
        clean.append(geometry(point["x"], point["y"]))
    return clean


def stable_seed(*parts):
    """Create a stable positive integer seed from identifiers."""
    payload = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0x7FFFFFFF


def normalized_arms(config):
    """Return [(arm, probability), ...] from study config.

    Accepted config form::
        {"arms": {"main": 0.8, "prime_positive": 0.1, "prime_negative": 0.1}}

    If no arms are provided, every participant is assigned ``main``.
    """
    arms = (config or {}).get("arms") or {"main": 1.0}
    if not isinstance(arms, dict) or not arms:
        raise ValueError("Study config 'arms' must be a non-empty object.")

    parsed = []
    total = 0.0
    for name, weight in arms.items():
        name = str(name).strip()
        weight = float(weight)
        if not name or weight < 0:
            raise ValueError("Arm names must be non-empty and weights non-negative.")
        if weight == 0:
            continue
        parsed.append((name, weight))
        total += weight
    if total <= 0:
        raise ValueError("At least one arm must have positive weight.")
    return [(name, weight / total) for name, weight in parsed]


def choose_arm(config, seed):
    rng = random.Random(seed)
    draw = rng.random()
    cumulative = 0.0
    arms = normalized_arms(config)
    for name, probability in arms:
        cumulative += probability
        if draw <= cumulative:
            return name
    return arms[-1][0]


def _get(item, name, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def build_schedule(items, arm="main", seed=1, min_target_lag=8):
    """Return items in a reproducible participant-specific experimental order.

    Every item is shown exactly once. Within each target group, the default
    sequence is isolated item first and contextual variants later. If the
    participant arm matches a contextual item's ``prime_arm``, that designated
    context becomes the first presentation and the isolated item becomes the
    second presentation for that target.

    Target groups are then interleaved in rounds: at most one item from a target
    appears in a round. This maximizes the separation between repeated targets
    and, for the main arm, has the useful experimental property that the first
    round consists entirely of context-free lexical baselines. When groups have
    equal numbers of variants, repeated targets are separated by all other
    active target groups. If only a few groups remain in a late round, the
    requested ``min_target_lag`` can become mathematically impossible; no item is
    duplicated or dropped in that case.
    """
    if min_target_lag < 0:
        raise ValueError("min_target_lag cannot be negative")

    active_items = [item for item in items if bool(_get(item, "active", True))]
    if not active_items:
        return []

    groups = defaultdict(list)
    for item in active_items:
        group = str(_get(item, "target_group") or _get(item, "target") or "").strip()
        if not group:
            raise ValueError("Each item needs target_group or target.")
        groups[group].append(item)

    rng = random.Random(seed)
    queues = {}
    for group, group_items in groups.items():
        isolated = [i for i in group_items if _get(i, "condition") == "isolated"]
        if len(isolated) > 1:
            raise ValueError(f"Target group {group!r} has more than one isolated item.")

        prime_candidates = [
            i for i in group_items
            if _get(i, "prime_arm") and str(_get(i, "prime_arm")) == str(arm)
        ]
        if len(prime_candidates) > 1:
            raise ValueError(
                f"Target group {group!r} has more than one prime item for arm {arm!r}."
            )
        prime = prime_candidates[0] if prime_candidates else None

        rest = [i for i in group_items if i not in isolated and i is not prime]
        rng.shuffle(rest)

        sequence = []
        if prime is not None:
            sequence.append(prime)
        if isolated:
            sequence.extend(isolated)
        sequence.extend(rest)
        queues[group] = sequence

    # One stable randomized target order per participant. Using the same cyclic
    # order in each round avoids the short boundary gaps that occur when every
    # round is independently shuffled.
    group_order = list(queues)
    rng.shuffle(group_order)

    schedule = []
    while any(queues[group] for group in group_order):
        for group in group_order:
            if queues[group]:
                schedule.append(queues[group].pop(0))

    return schedule
