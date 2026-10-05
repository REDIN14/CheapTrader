"""How many bars an indicator is run over.

An indicator is run over as many bars as the chart shows (its history depth: 20,000 by default, up to 100,000), so that
its lines reach back as far as the candles do. Some indicators need more than that to work at all: an average over 50,000
bars cannot be drawn from 20,000. Such an indicator says so with one line at the top level of its code::

    NEEDS_BARS = 60_000

The line is read from the code without running it (``declared_bars``), which is why it is a plain whole number or a sum
or product of them, not something computed from the parameters: write the most the indicator may need. The bars it asks
for are loaded as well as the ones on the chart, and only the lines over the chart's own bars come back; the older ones
are there to warm the indicator up. Where the broker has fewer bars than that, the indicator gets what there is.
"""

from __future__ import annotations

import ast

#: The name of the line an indicator writes to say how many bars it needs.
NEEDS_NAME = "NEEDS_BARS"
#: The most bars an indicator is ever run over (a bigger ``NEEDS_BARS`` is cut down to this).
MAX_INDICATOR_BARS = 200_000
#: The most bars a request may ask to see the lines over: the deepest chart there is (the same as ``GET /api/bars``).
MAX_SHOWN_BARS = 100_000


def _whole_number(node: ast.expr) -> int | None:
    """The value of a whole number written as digits, signs and ``+ - * //`` (nothing else is evaluated)."""
    if isinstance(node, ast.Constant):
        return node.value if type(node.value) is int else None  # not a float, and not True / False
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        inner = _whole_number(node.operand)
        if inner is None:
            return None
        return inner if isinstance(node.op, ast.UAdd) else -inner
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv)):
        left, right = _whole_number(node.left), _whole_number(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left // right if right else None
    return None


def declared_bars(code: str) -> int | None:
    """The number of bars an indicator says it needs (``NEEDS_BARS = 60_000``), or None when it says nothing (or says
    something that is not a positive whole number). Only a top-level line counts, and the last one wins, as in Python."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    declared: int | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == NEEDS_NAME for t in targets):
            declared = _whole_number(value)
    return declared if declared is not None and declared > 0 else None


def bars_to_load(shown: int, declared: int | None) -> int:
    """How many of the newest bars to run the indicator over: the ones whose lines are wanted, or the ones the
    indicator says it needs when that is more."""
    if not declared:
        return shown
    return max(shown, min(declared, MAX_INDICATOR_BARS))
