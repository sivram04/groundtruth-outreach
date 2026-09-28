"""Business days for follow-up timing, counted on New York dates.

Founder decisions:
- 2026-09-22: a follow-up is due on the third business day after the previous email was
  actually sent. The first business day after the send is day 1.
- 2026-09-28: weekends and the major US holidays are skipped — New Year's Day, Memorial Day,
  Independence Day, Labor Day, Thanksgiving and the day after, and Christmas Day. Columbus Day,
  Veterans Day and the other federal holidays are ordinary business days.

A fixed-date holiday that falls on a Saturday is taken on the Friday before, and one that falls
on a Sunday on the Monday after. That is the usual US practice; it was chosen here, not stated
by the founder.
"""

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
FOLLOWUP_GAP = 3  # business days between an email actually sent and the next follow-up


def _nth_weekday(year, month, weekday, n):
    """The n-th `weekday` (Monday is 0) of a month; n = -1 is the last one."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    after = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = after - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day):
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=None)
def holidays(year):
    """The days off in `year`, as taken (a weekend holiday moves to the nearest weekday)."""
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    return frozenset({
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 5, 0, -1),  # Memorial Day, last Monday of May
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day, first Monday of September
        thanksgiving,
        thanksgiving + timedelta(days=1),
        _observed(date(year, 12, 25)),
    })


def is_business_day(day):
    # New Year's Day on a Saturday is taken on 31 December of the year before.
    return day.weekday() < 5 and day not in holidays(day.year) | holidays(day.year + 1)


def add_business_days(start, n):
    """The n-th business day after `start`; the first business day after it is day 1."""
    day, counted = start, 0
    while counted < n:
        day += timedelta(days=1)
        if is_business_day(day):
            counted += 1
    return day


def new_york_date(moment):
    """The New York calendar date of an aware datetime."""
    return moment.astimezone(NEW_YORK).date()


def today():
    return datetime.now(NEW_YORK).date()
