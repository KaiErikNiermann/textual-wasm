"""Legitimate shapes the rules must NOT flag.

Guards against the append-only-loop rule degenerating into a false-positive machine:
`...` matches zero or more statements, so the natural way to write its exclusions
cancels the rule, and the natural fix over-matches multi-statement loops.
"""


def multi_statement_loop(items: list[int]) -> list[int]:
    out: list[int] = []
    for item in items:
        doubled = item * 2
        out.append(doubled)
    return out


def guarded_loop(items: list[int]) -> list[int]:
    out: list[int] = []
    for item in items:
        if item > 0:
            out.append(item)
    return out
