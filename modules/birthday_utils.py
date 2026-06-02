from datetime import date


def calculate_current_age(birth_day, birth_month, birth_year, reference_date=None):
    """Return the person's current age as an int, or None if birth_year is missing.

    Handles Feb 29 birthdays correctly: in a non-leap reference year the
    birthday is considered not-yet-passed until Mar 1.  We use plain tuple
    comparison so we never construct an invalid date(year, 2, 29).
    """
    if birth_year is None:
        return None
    if reference_date is None:
        reference_date = date.today()
    age = reference_date.year - birth_year
    if (reference_date.month, reference_date.day) < (birth_month, birth_day):
        age -= 1
    return age


def calculate_turning_age(birth_year, birthday_year):
    """Return the age the person turns in *birthday_year*, or None."""
    if birth_year is None or birthday_year is None:
        return None
    return birthday_year - birth_year
