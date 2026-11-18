"""Business limits shared by every form / endpoint that takes a number.

The database columns are plain 32-bit integers, so without an upper bound a
typo (or a crafted request) such as 99999999999 is accepted by SQLite but
crashes Postgres with "integer out of range" (HTTP 500 in production).
These caps are far above any real value and only exist to turn that crash
into a normal validation message.
"""

MAX_QUANTITY  = 1_000_000   # units in one hour (planned, actual or scrap)
MAX_HEADCOUNT = 1_000       # people in one plan / one hour


def check_quantity(value, label="Quantity"):
    """Return an error message when `value` (an int) is outside 0..MAX_QUANTITY."""
    if value < 0:
        return f"{label} cannot be negative."
    if value > MAX_QUANTITY:
        return f"{label} cannot be greater than {MAX_QUANTITY:,}."
    return None


def check_headcount(value, label="Headcount", minimum=1):
    """Return an error message when `value` (an int) is outside minimum..MAX_HEADCOUNT."""
    if value < minimum:
        return f"{label} must be at least {minimum}."
    if value > MAX_HEADCOUNT:
        return f"{label} cannot be greater than {MAX_HEADCOUNT:,}."
    return None
