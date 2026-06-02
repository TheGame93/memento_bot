"""modules/zodiac.py — Western and Eastern zodiac computation engine.

Pure Python, no external dependencies. Safe to import anywhere.

Public API:
    get_western_zodiac(day, month) -> dict | None
    get_eastern_zodiac(day, month, year) -> dict | None
    get_zodiac_info(day, month, year=None) -> dict
    format_western_line(western) -> str
    format_eastern_line(eastern) -> str
"""

# ===========================================================================
# WESTERN ZODIAC
# ===========================================================================

# Each entry: (name_it, element_it, (start_month, start_day), (end_month, end_day), date_range_str)
# Capricorn is listed first; its Dec-Jan wraparound is handled in the lookup.
_WESTERN_SIGNS = [
    ("Capricorno", "Terra",  (12, 22), (1,  19), "22/12\u201319/01"),
    ("Acquario",   "Aria",   (1,  20), (2,  18), "20/01\u201318/02"),
    ("Pesci",      "Acqua",  (2,  19), (3,  20), "19/02\u201320/03"),
    ("Ariete",     "Fuoco",  (3,  21), (4,  19), "21/03\u201319/04"),
    ("Toro",       "Terra",  (4,  20), (5,  20), "20/04\u201320/05"),
    ("Gemelli",    "Aria",   (5,  21), (6,  20), "21/05\u201320/06"),
    ("Cancro",     "Acqua",  (6,  21), (7,  22), "21/06\u201322/07"),
    ("Leone",      "Fuoco",  (7,  23), (8,  22), "23/07\u201322/08"),
    ("Vergine",    "Terra",  (8,  23), (9,  22), "23/08\u201322/09"),
    ("Bilancia",   "Aria",   (9,  23), (10, 22), "23/09\u201322/10"),
    ("Scorpione",  "Acqua",  (10, 23), (11, 21), "23/10\u201321/11"),
    ("Sagittario", "Fuoco",  (11, 22), (12, 21), "22/11\u201321/12"),
]


def _western_sign_contains(sign, month, day):
    _name, _elem, start, end, _dr = sign
    date = (month, day)
    if start <= end:
        return start <= date <= end
    # Wraparound case (Capricorn: Dec 22 – Jan 19)
    return date >= start or date <= end


# ===========================================================================
# EASTERN ZODIAC
# ===========================================================================

# Anchored to 1900 = Rat (index 0). Animal index = (chinese_year - 1900) % 12.
_EASTERN_ANIMALS = [
    "Ratto", "Bue", "Tigre", "Coniglio", "Drago", "Serpente",
    "Cavallo", "Capra", "Scimmia", "Gallo", "Cane", "Maiale",
]

# Element: keyed by chinese_year % 10 (last digit of Chinese year).
_EASTERN_ELEMENTS = {
    0: "Metallo", 1: "Metallo",
    2: "Acqua",   3: "Acqua",
    4: "Legno",   5: "Legno",
    6: "Fuoco",   7: "Fuoco",
    8: "Terra",   9: "Terra",
}

# Chinese New Year (Gregorian) dates for 1900–2100.
# Key = Gregorian year, value = (month, day) of the first day of that Chinese year.
# Sources: historical astronomical records for 1900–2030; Metonic cycle
# projections (19-year cycle, ±1 day drift per cycle) for 2031–2100.
_CHINESE_NEW_YEAR = {
    1900: (1, 31), 1901: (2, 19), 1902: (2,  8), 1903: (1, 29), 1904: (2, 16),
    1905: (2,  4), 1906: (1, 25), 1907: (2, 13), 1908: (2,  2), 1909: (1, 22),
    1910: (2, 10), 1911: (1, 30), 1912: (2, 18), 1913: (2,  6), 1914: (1, 26),
    1915: (2, 14), 1916: (2,  3), 1917: (1, 23), 1918: (2, 11), 1919: (2,  1),
    1920: (2, 20), 1921: (2,  8), 1922: (1, 28), 1923: (2, 16), 1924: (2,  5),
    1925: (1, 25), 1926: (2, 13), 1927: (2,  2), 1928: (1, 23), 1929: (2, 10),
    1930: (1, 30), 1931: (2, 17), 1932: (2,  6), 1933: (1, 26), 1934: (2, 14),
    1935: (2,  4), 1936: (1, 24), 1937: (2, 11), 1938: (1, 31), 1939: (2, 19),
    1940: (2,  8), 1941: (1, 27), 1942: (2, 15), 1943: (2,  5), 1944: (1, 25),
    1945: (2, 13), 1946: (2,  2), 1947: (1, 22), 1948: (2, 10), 1949: (1, 29),
    1950: (2, 17), 1951: (2,  6), 1952: (1, 27), 1953: (2, 14), 1954: (2,  3),
    1955: (1, 24), 1956: (2, 12), 1957: (1, 31), 1958: (2, 18), 1959: (2,  8),
    1960: (1, 28), 1961: (2, 15), 1962: (2,  5), 1963: (1, 25), 1964: (2, 13),
    1965: (2,  2), 1966: (1, 21), 1967: (2,  9), 1968: (1, 30), 1969: (2, 17),
    1970: (2,  6), 1971: (1, 27), 1972: (2, 15), 1973: (2,  3), 1974: (1, 23),
    1975: (2, 11), 1976: (1, 31), 1977: (2, 18), 1978: (2,  7), 1979: (1, 28),
    1980: (2, 16), 1981: (2,  5), 1982: (1, 25), 1983: (2, 13), 1984: (2,  2),
    1985: (2, 20), 1986: (2,  9), 1987: (1, 29), 1988: (2, 17), 1989: (2,  6),
    1990: (1, 27), 1991: (2, 15), 1992: (2,  4), 1993: (1, 23), 1994: (2, 10),
    1995: (1, 31), 1996: (2, 19), 1997: (2,  7), 1998: (1, 28), 1999: (2, 16),
    2000: (2,  5), 2001: (1, 24), 2002: (2, 12), 2003: (2,  1), 2004: (1, 22),
    2005: (2,  9), 2006: (1, 29), 2007: (2, 18), 2008: (2,  7), 2009: (1, 26),
    2010: (2, 14), 2011: (2,  3), 2012: (1, 23), 2013: (2, 10), 2014: (1, 31),
    2015: (2, 19), 2016: (2,  8), 2017: (1, 28), 2018: (2, 16), 2019: (2,  5),
    2020: (1, 25), 2021: (2, 12), 2022: (2,  1), 2023: (1, 22), 2024: (2, 10),
    2025: (1, 29), 2026: (2, 17), 2027: (2,  6), 2028: (1, 26), 2029: (2, 13),
    2030: (2,  3), 2031: (1, 23), 2032: (2, 11), 2033: (1, 31), 2034: (2, 19),
    2035: (2,  8), 2036: (1, 28), 2037: (2, 15), 2038: (2,  4), 2039: (1, 24),
    2040: (2, 12), 2041: (2,  1), 2042: (1, 22), 2043: (2, 10), 2044: (1, 30),
    2045: (2, 17), 2046: (2,  6), 2047: (1, 26), 2048: (2, 14), 2049: (2,  2),
    2050: (1, 23), 2051: (2, 11), 2052: (1, 31), 2053: (2, 18), 2054: (2,  8),
    2055: (1, 27), 2056: (2, 15), 2057: (2,  3), 2058: (1, 24), 2059: (2, 12),
    2060: (2,  1), 2061: (1, 21), 2062: (2,  9), 2063: (1, 29), 2064: (2, 17),
    2065: (2,  5), 2066: (1, 26), 2067: (2, 13), 2068: (2,  2), 2069: (1, 22),
    2070: (2, 10), 2071: (1, 31), 2072: (2, 19), 2073: (2,  7), 2074: (1, 27),
    2075: (2, 15), 2076: (2,  4), 2077: (1, 23), 2078: (2, 11), 2079: (2,  1),
    2080: (1, 21), 2081: (2,  8), 2082: (1, 28), 2083: (2, 16), 2084: (2,  5),
    2085: (1, 25), 2086: (2, 12), 2087: (2,  1), 2088: (1, 21), 2089: (2,  9),
    2090: (1, 29), 2091: (2, 17), 2092: (2,  6), 2093: (1, 26), 2094: (2, 14),
    2095: (2,  3), 2096: (1, 23), 2097: (2, 10), 2098: (1, 31), 2099: (2, 18),
    2100: (2,  8),
}


# ===========================================================================
# PUBLIC FUNCTIONS
# ===========================================================================

def get_western_zodiac(day: int, month: int) -> dict | None:
    """Return Western zodiac info for (day, month), or None if invalid.

    Returns dict with keys: sign, element, date_range (all Italian strings).
    Handles Capricorn's Dec-Jan wraparound.
    Does NOT require a valid calendar date; any day 1-31, month 1-12 is accepted.
    """
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    for sign in _WESTERN_SIGNS:
        if _western_sign_contains(sign, month, day):
            name, element, _start, _end, date_range = sign
            return {"sign": name, "element": element, "date_range": date_range}
    return None  # should never be reached for valid input


def get_eastern_zodiac(day: int, month: int, year: int) -> dict | None:
    """Return Eastern (Chinese) zodiac info for (day, month, year), or None.

    Returns None when year is outside the lookup table range (< 1900 or > 2100).
    Uses the Chinese New Year date to determine whether the birthday falls in
    the given Gregorian year's Chinese year or the previous one.

    Returns dict with keys: animal, yin_yang, element, chinese_year.
    """
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None

    cny = _CHINESE_NEW_YEAR.get(year)
    if cny is None:
        return None  # year out of table range

    birthday = (month, day)
    if birthday >= cny:
        chinese_year = year
    else:
        chinese_year = year - 1

    animal = _EASTERN_ANIMALS[(chinese_year - 1900) % 12]
    element = _EASTERN_ELEMENTS[chinese_year % 10]
    yin_yang = "Yang" if chinese_year % 2 == 0 else "Yin"

    return {
        "animal": animal,
        "yin_yang": yin_yang,
        "element": element,
        "chinese_year": chinese_year,
    }


def get_zodiac_info(day: int, month: int, year: int | None = None) -> dict:
    """Return combined zodiac info dict with keys: western, eastern.

    western: always attempted; None if day/month are invalid.
    eastern: only computed when year is not None; None otherwise or on error.
    """
    western = get_western_zodiac(day, month)
    eastern = None
    if year is not None:
        eastern = get_eastern_zodiac(day, month, year)
    return {"western": western, "eastern": eastern}


def format_western_line(western: dict) -> str:
    """Format a Western zodiac dict as a compact line.

    Example: "Sagittario (22/11\u201321/12) \u00b7 Fuoco"
    """
    return f"{western['sign']} ({western['date_range']}) \u00b7 {western['element']}"


def format_eastern_line(eastern: dict) -> str:
    """Format an Eastern zodiac dict as a compact line.

    Example: "Drago \u00b7 Yang \u00b7 Legno"
    """
    return f"{eastern['animal']} \u00b7 {eastern['yin_yang']} \u00b7 {eastern['element']}"
