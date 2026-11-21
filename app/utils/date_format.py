"""A date written in a pattern: the one a column shows its dates in, in the table and on a chart's axis.

The pattern is written as YYYY-MM-DD HH:mm or in strftime codes (import_cleaning.date_format_to_strftime). Month
and day names (%b %B %a %A) come out in this computer's language, as the parser reads them back; the numbers
never depend on it.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.utils.import_cleaning import date_format_to_strftime

_NAMES = re.compile(r"%%|%[bBaA]")


def localized_strftime(moment: Any, pattern: str) -> str:
    """*moment* (a datetime or pandas Timestamp) in *pattern*, with this computer's month and day names."""
    strftime_pattern = date_format_to_strftime(pattern)
    if "%" not in strftime_pattern:
        return strftime_pattern
    try:
        from PySide6.QtCore import QLocale

        locale = QLocale.system()
    except Exception:  # no Qt (a script): the names strftime gives
        return moment.strftime(strftime_pattern)

    def name(match: re.Match[str]) -> str:
        code = match.group(0)
        if code == "%%":
            return code
        if code in ("%b", "%B"):
            form = QLocale.FormatType.ShortFormat if code == "%b" else QLocale.FormatType.LongFormat
            return locale.monthName(moment.month, form).replace("%", "%%")
        form = QLocale.FormatType.ShortFormat if code == "%a" else QLocale.FormatType.LongFormat
        return locale.dayName(moment.isoweekday(), form).replace("%", "%%")

    return moment.strftime(_NAMES.sub(name, strftime_pattern))


def is_valid_pattern(pattern: str) -> bool:
    """Whether *pattern* writes a date (a moment is formatted with it without an error)."""
    try:
        localized_strftime(datetime(2024, 12, 31, 13, 5, 9), pattern)
    except (ValueError, TypeError):
        return False
    return True
