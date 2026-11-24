"""What the import makes of missing values and dates: shared by the Import dialog and a link's refresh.

* Missing values: codes that mean "no value" ("NA", "n/d", "-", "#N/A"...)
  and, unless asked otherwise, empty or blank text become empty cells, so
  that a numeric column with "n/d" in it is read as numbers.
* Dates: text dates are recognised and converted, in the order the user
  says - day first (31/12/2024), month first (12/31/2024), year first
  (2024-12-31), or an explicit format (%d.%m.%Y %H:%M) - or, by default,
  in the order the values themselves show, as pandas guesses: a first
  number above 12 is a day, a second above 12 makes the first a month, four
  digits first is a year. When nothing tells (01/02/2024), the computer's
  own date order decides.

No Qt: app.utils.import_runner refreshes a link with the same rules.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

import pandas as pd

from app.utils.coercion import to_numbers

AUTO, DAY_FIRST, MONTH_FIRST, YEAR_FIRST, FORMAT = "auto", "dayfirst", "monthfirst", "yearfirst", "format"
DATE_ORDERS: tuple[tuple[str, str], ...] = (
    (AUTO, "Auto (from the values)"), (DAY_FIRST, "Day first (31/12/2024)"),
    (MONTH_FIRST, "Month first (12/31/2024)"), (YEAR_FIRST, "Year first (2024-12-31)"),
    (FORMAT, "Format..."),
)
#: Read as empty, besides empty text: what spreadsheets and instruments write for "no value".
DEFAULT_MISSING: tuple[str, ...] = (
    "NA", "N/A", "NaN", "null", "None", "-", "--", "?", "n/d", "n.d.", "#N/A", "#VALUE!", "#DIV/0!", "#NUM!",
)
_DATE_LIKE = re.compile(r"^\s*(\d{1,4})[./\-](\d{1,2})[./\-](\d{1,4})(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?\s*$")
_MONTH_NAME = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|gen|mag|giu|lug|ago|set|ott|dic)",
                         re.IGNORECASE)


_ENGLISH_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
                   "september", "october", "november", "december")
_ENGLISH_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
#: The notation people write a date format in, and the strftime code each stands for. Longest first.
_FORMAT_TOKENS = re.compile(r"YYYY|YY|MMMM|MMM|MM|M|DD|D|dddd|ddd|HH|H|hh|h|mm|m|ss|s|A|a")
_FORMAT_CODES = {
    "YYYY": "%Y", "YY": "%y", "MMMM": "%B", "MMM": "%b", "MM": "%m", "M": "%m", "DD": "%d", "D": "%d",
    "dddd": "%A", "ddd": "%a", "HH": "%H", "H": "%H", "hh": "%I", "h": "%I", "mm": "%M", "m": "%M",
    "ss": "%S", "s": "%S", "A": "%p", "a": "%p",
}


def date_format_to_strftime(text: str) -> str:
    """A date format as strftime codes: "DD/MM/YYYY HH:mm" becomes "%d/%m/%Y %H:%M".

    Text with a "%" in it is strftime already and is left as it is.
    """
    text = str(text or "").strip()
    if "%" in text:
        return text
    return _FORMAT_TOKENS.sub(lambda match: _FORMAT_CODES[match.group(0)], text)


def _fold(word: str) -> str:
    """Lower case, accents and the dot of an abbreviation gone: "Févr." and "fevr" are one word."""
    plain = unicodedata.normalize("NFD", word.lower().strip().rstrip("."))
    return "".join(char for char in plain if not unicodedata.combining(char))


_local_names_cache: dict[str, tuple[re.Pattern[str], dict[str, str]]] = {}


def _local_names(locale_name: str | None = None) -> tuple[re.Pattern[str], dict[str, str]] | None:
    """This computer's month and day names (long and short), as a pattern and the English each stands for.

    English is always read; these are the names of the system's own language, from Qt's locale data. A name
    that is also an English one is left out: it already means what English says.
    """
    from PySide6.QtCore import QLocale

    locale = QLocale(locale_name) if locale_name else QLocale.system()
    key = locale.name()
    if key not in _local_names_cache:
        english = set(_ENGLISH_MONTHS) | set(_ENGLISH_DAYS) | {name[:3] for name in _ENGLISH_MONTHS + _ENGLISH_DAYS}
        mapping: dict[str, str] = {}
        written: set[str] = set()  # the names as the locale writes them, accents kept, beside the folded ones
        for index in range(1, 13):
            for form in (QLocale.FormatType.LongFormat, QLocale.FormatType.ShortFormat):
                name = locale.monthName(index, form)
                mapping[_fold(name)] = _ENGLISH_MONTHS[index - 1][:3]
                written.add(name.lower().rstrip("."))
        for index in range(1, 8):
            for form in (QLocale.FormatType.LongFormat, QLocale.FormatType.ShortFormat):
                name = locale.dayName(index, form)
                mapping[_fold(name)] = _ENGLISH_DAYS[index - 1][:3]
                written.add(name.lower().rstrip("."))
        mapping = {name: eng for name, eng in mapping.items() if name and name not in english and name.isalpha()}
        words = sorted(set(mapping) | {w for w in written if _fold(w) in mapping}, key=len, reverse=True)
        pattern = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b\.?", re.IGNORECASE) if words else None
        _local_names_cache[key] = (pattern, mapping)  # type: ignore[assignment]
    pattern, mapping = _local_names_cache[key]
    return (pattern, mapping) if pattern is not None else None


def english_names(text: pd.Series, locale_name: str | None = None) -> pd.Series:
    """*text* with the month and day names of this computer's language written in English, for the parser.

    Accents are tolerated ("févr", "fevr") and so is the dot of an abbreviation ("janv.").
    """
    found = _local_names(locale_name)
    if found is None:
        return text
    pattern, mapping = found

    def swap(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return pattern.sub(lambda match: mapping.get(_fold(match.group(1)), match.group(0)), value)

    return text.map(swap).astype("string")


def parse_missing(text: str) -> list[str]:
    """The codes in a comma-separated field."""
    return [code.strip() for code in str(text or "").split(",") if code.strip()]


def matches_missing(values: pd.Series, codes: Iterable[str]) -> pd.Series:
    """Where *values* hold one of the missing-value *codes*: as text, the case ignored ("na" is "NA"), or as
    a number (-999 matches -999.0). Empty cells are no match: they are missing already."""
    wanted = [str(code).strip() for code in codes if str(code).strip()]
    hits = pd.Series(False, index=values.index)
    if not wanted:
        return hits
    text = values.astype("string").str.strip().str.lower()
    hits |= text.isin([code.lower() for code in wanted]).fillna(False).astype(bool)
    numbers = to_numbers(pd.Series(wanted)).dropna()
    if not numbers.empty:
        hits |= to_numbers(values).isin(numbers.to_numpy()).fillna(False).astype(bool)
    return hits & values.notna()


def clean_missing(frame: pd.DataFrame, codes: Iterable[str] = DEFAULT_MISSING, *,
                  empty_is_missing: bool = True) -> pd.DataFrame:
    """*frame* with the missing codes - and empty or blank text - as empty cells (text columns only)."""
    wanted = {str(code).strip().lower() for code in codes if str(code).strip()}
    result = frame.copy()
    for name in result.columns:
        column = result[name]
        if not (pd.api.types.is_object_dtype(column) or pd.api.types.is_string_dtype(column)):
            continue
        text = column.astype("string").str.strip()
        missing = text.str.lower().isin(wanted).fillna(False)
        if empty_is_missing:
            missing |= (text == "").fillna(False)
        if missing.any():
            result[name] = column.mask(missing.to_numpy(bool), None)
    return result


def guess_date_order(values: Iterable[Any], default: str = MONTH_FIRST) -> str:
    """The order the dates in *values* are written in: what their numbers show, else *default*."""
    day_first = month_first = year_first = False
    for value in values:
        match = _DATE_LIKE.match(str(value))
        if not match:
            continue
        first, second = match.group(1), match.group(2)
        if len(first) == 4:
            year_first = True
        elif int(first) > 12:
            day_first = True
        elif int(second) > 12:
            month_first = True
    if year_first:
        return YEAR_FIRST
    if day_first and not month_first:
        return DAY_FIRST
    if month_first and not day_first:
        return MONTH_FIRST
    return default


def parse_dates(series: pd.Series, order: str = AUTO, date_format: str = "", *,
                default: str = MONTH_FIRST) -> pd.Series:
    """*series* as datetimes (NaT where a value is no date), in the *order* or *date_format* given."""
    text = series.astype("string")
    if not pd.api.types.is_datetime64_any_dtype(series):
        text = english_names(text)
    if order == FORMAT and date_format.strip():
        return pd.to_datetime(text, format=date_format_to_strftime(date_format), errors="coerce")
    if order == AUTO:
        order = guess_date_order(text.dropna().head(500), default)
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    return pd.to_datetime(text, errors="coerce", format="mixed", dayfirst=order == DAY_FIRST,
                          yearfirst=order == YEAR_FIRST)


def looks_like_dates(series: pd.Series, order: str = AUTO, date_format: str = "", *,
                     default: str = MONTH_FIRST) -> bool:
    """True when nearly every value of a text column is a date (and it is not plain numbers)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return False
    sample = series.dropna().astype(str).head(200)
    if sample.empty or to_numbers(sample).notna().all():
        return False
    shaped = english_names(sample).map(lambda v: bool(_DATE_LIKE.match(v) or _MONTH_NAME.search(v)))
    if shaped.mean() < 0.9:
        return False
    return bool(parse_dates(sample, order, date_format, default=default).notna().mean() >= 0.9)


def date_kind(series: pd.Series, order: str = AUTO, date_format: str = "", *, default: str = MONTH_FIRST) -> str:
    """DATE when every parsed value is at midnight, else DATETIME."""
    parsed = parse_dates(series, order, date_format, default=default).dropna()
    if not parsed.empty and (parsed.dt.normalize() == parsed).all():
        return "DATE"
    return "DATETIME"


def convert_dates(series: pd.Series, kind: str, order: str = AUTO, date_format: str = "", *,
                  default: str = MONTH_FIRST) -> pd.Series:
    """DATE, TIME or DATETIME as ISO text ("2024-12-31", "13:05:00", "2024-12-31 13:05:00")."""
    parsed = parse_dates(series, order, date_format, default=default)
    pattern = {"DATE": "%Y-%m-%d", "TIME": "%H:%M:%S"}.get(kind, "%Y-%m-%d %H:%M:%S")
    return parsed.dt.strftime(pattern).astype("string")


def read_settings(read: dict[str, Any]) -> tuple[list[str], bool, str, str]:
    """(missing codes, empty is missing, date order, date format) from a link's "read" settings."""
    codes = read.get("missing")
    return (list(DEFAULT_MISSING) if codes is None else [str(code) for code in codes],
            bool(read.get("empty_is_missing", True)), str(read.get("dates") or AUTO),
            str(read.get("date_format") or ""))
