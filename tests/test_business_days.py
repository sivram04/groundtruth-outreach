"""Follow-up timing: the third business day, weekends and the major US holidays skipped."""

from datetime import date

import pytest

from outreach.business_days import add_business_days, holidays, is_business_day


@pytest.mark.parametrize("sent,due", [
    # The founder's 14 hand-sent emails: Tuesday -> Friday.
    (date(2026, 9, 22), date(2026, 9, 25)),
    # A Friday send skips the weekend.
    (date(2026, 10, 2), date(2026, 10, 7)),
    # Columbus Day is an ordinary business day under the founder's choice of major holidays.
    (date(2026, 10, 9), date(2026, 10, 14)),
    # Thanksgiving and the day after are skipped.
    (date(2026, 11, 25), date(2026, 12, 2)),
    # Christmas 2026 is a Friday.
    (date(2026, 12, 23), date(2026, 12, 29)),
    # A weekend send counts from Monday.
    (date(2026, 9, 26), date(2026, 9, 30)),
])
def test_the_third_business_day(sent, due):
    assert add_business_days(sent, 3) == due


def test_the_major_holidays_of_2026():
    assert holidays(2026) == {date(2026, 1, 1), date(2026, 5, 25), date(2026, 7, 3),
                              date(2026, 9, 7), date(2026, 11, 26), date(2026, 11, 27),
                              date(2026, 12, 25)}


def test_a_saturday_holiday_is_taken_on_the_friday_before():
    assert not is_business_day(date(2026, 7, 3))  # 4 July 2026 is a Saturday


def test_new_years_day_on_a_saturday_is_taken_the_year_before():
    assert date(2028, 1, 1).weekday() == 5
    assert not is_business_day(date(2027, 12, 31))


def test_federal_holidays_outside_the_major_ones_are_business_days():
    for day in (date(2026, 10, 12), date(2026, 11, 11), date(2026, 6, 19), date(2026, 1, 19)):
        assert is_business_day(day), day
