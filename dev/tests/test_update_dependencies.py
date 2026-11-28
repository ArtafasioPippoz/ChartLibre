"""The library-update check reports only what is behind."""
from __future__ import annotations

from dev.tools.update_dependencies import outdated


def test_only_the_libraries_behind_are_reported() -> None:
    report = {"install": [
        {"metadata": {"name": "numpy", "version": "3.1.0"}},
        {"metadata": {"name": "Scikit_Learn", "version": "1.9.0"}},
        {"metadata": {"name": "pandas", "version": "3.0.2"}},
        {"metadata": {"name": "brand-new", "version": "0.1"}},
    ]}
    before = {"numpy": "3.0.0", "scikit-learn": "1.8.1", "pandas": "3.0.2"}
    assert outdated(report, before) == [("brand-new", "-", "0.1"), ("numpy", "3.0.0", "3.1.0"),
                                        ("Scikit_Learn", "1.8.1", "1.9.0")]
    assert outdated({}, before) == []
