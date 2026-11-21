"""Every SVG drawing of ChartLibre, in one place.

Each value is bare SVG body on a 24 x 24 box - no ``<svg>`` element:
``app.styles.style.icon_from_svg_source`` (or ``svg_icon_document``) wraps it
in the standard stroke-only document and inks it in the theme's colour.

Sections: the application's mark, the title bar's caption glyphs, the action
catalogue's drawn icons (by action id; config.json gives the system glyphs),
the Analysis panel's tools, and one icon per analysis plugin (its ``Icon``).
An extension pack keeps drawing its own: ``Icon`` stays a plain string.
"""

# ruff: noqa: E501

# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------

#: An open bracket graduated like a ruler, with a small chart breaking out past it.
APP: str = '<path d="M11 5H7v14h4"/><path d="M4 9h3M4 15h3"/><path d="M10 16l5-6 4-5"/>'

# ---------------------------------------------------------------------------
# Title bar (Windows): the four caption glyphs
# ---------------------------------------------------------------------------

CAPTION: dict[str, str] = {
    "minimize": '<path d="M5 12h14"/>',
    "maximize": '<rect x="5" y="5" width="14" height="14" rx="1"/>',
    "restore": '<path d="M8 8V5h11v11h-3"/><rect x="5" y="8" width="11" height="11" rx="1"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
}

# ---------------------------------------------------------------------------
# Action catalogue: drawn where no system set has the glyph (by action id)
# ---------------------------------------------------------------------------

ACTIONS: dict[str, str] = {
    "table_edit": '<path d="M11 17H4.5A1.5 1.5 0 0 1 3 15.5v-11A1.5 1.5 0 0 1 4.5 3h11A1.5 1.5 0 0 1 17 4.5V10M3 7.7h14M3 12.3h9M7.7 3v14M12.3 3v8"/><path d="M19.2 11.3l2.5 2.5-7.2 7.2H12v-2.5zM17.5 13l2.5 2.5"/>',
    "table_group_aggregate": '<path d="M17.5 4.5h-11l6 7.5-6 7.5h11"/>',
    "table_add_row": '<rect x="3" y="3.5" width="18" height="5" rx="1"/><rect x="3" y="10.5" width="10" height="5" rx="1"/><path d="M18.5 14v8M14.5 18h8"/>',
    "table_insert_row": '<path d="M12 2v6M9 5.5l3 3 3-3"/><rect x="3" y="11" width="18" height="4.5" rx="1"/><rect x="3" y="17.5" width="18" height="4.5" rx="1"/>',
    "table_delete_rows": '<g stroke="#D93025"><rect x="3" y="3.5" width="18" height="5" rx="1"/><rect x="3" y="10.5" width="10" height="5" rx="1"/><path d="M15.5 15.5l6 6M21.5 15.5l-6 6"/></g>',
    "table_add_column": '<rect x="3.5" y="3" width="5" height="18" rx="1"/><rect x="10.5" y="3" width="5" height="10" rx="1"/><path d="M18.5 14v8M14.5 18h8"/>',
    "table_insert_column": '<path d="M2 12h6M5.5 9l3 3-3 3"/><rect x="11" y="3" width="4.5" height="18" rx="1"/><rect x="17.5" y="3" width="4.5" height="18" rx="1"/>',
    "table_rename_column": '<rect x="3.5" y="3" width="5.5" height="18" rx="1"/><path d="M12.5 21l1-4 6.2-6.2a1.6 1.6 0 0 1 2.3 2.3L15.8 19.3z"/><path d="M12 5h8"/>',
    "table_computed_column": '<rect x="3.5" y="3" width="5.5" height="18" rx="1"/><path d="M21 4.5c-2.6-.6-4 .5-4.4 3L15 19.5c-.4 2.2-1.7 2.8-3 2.4"/><path d="M13.5 10.5h6"/>',
    "table_delete_column": '<g stroke="#D93025"><rect x="3.5" y="3" width="5" height="18" rx="1"/><rect x="10.5" y="3" width="5" height="10" rx="1"/><path d="M15.5 15.5l6 6M21.5 15.5l-6 6"/></g>',
    "table_cast_column": '<rect x="3.5" y="3" width="5.5" height="18" rx="1"/><path d="M12.5 4.5h8M16.5 4.5v7"/><path d="M12.5 17.5h9M18.5 14.5l3 3-3 3"/>',
    "table_sort_ascending": '<path d="M4 6.5h5M4 12h8M4 17.5h11"/><path d="M19 20V4M16 7l3-3 3 3"/>',
    "table_sort_descending": '<path d="M4 6.5h11M4 12h8M4 17.5h5"/><path d="M19 4v16M16 17l3 3 3-3"/>',
    "table_fill_missing": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/><path d="M12 10.5v3M10.5 12h3"/>',
}

# ---------------------------------------------------------------------------
# Analysis panel: tools that are not plugins
# ---------------------------------------------------------------------------

DOE: str = '<rect x="4" y="4" width="16" height="16" rx="2"/><circle cx="8" cy="8" r="1.4"/><circle cx="16" cy="8" r="1.4"/><circle cx="8" cy="16" r="1.4"/><circle cx="16" cy="16" r="1.4"/><circle cx="12" cy="12" r="1.4"/>'
PREDICT: str = '<circle cx="6" cy="17" r="1.6"/><circle cx="12" cy="11" r="1.6"/><circle cx="18" cy="6" r="1.6"/><path d="M4 20h16M4 20V4"/>'
PARETO: str = '<path d="M4 20V6M8 20V9M12 20v-7M16 20v-4M20 20v-2"/><path d="M4 6l4 -2 4 -1 4 -0.5 4 -0.3"/>'
ISHIKAWA: str = '<path d="M3 12h16l2 0"/><path d="M6 12l3-5M11 12l3-5M6 12l3 5M11 12l3 5"/><path d="M19 9l2 3-2 3"/>'

# ---------------------------------------------------------------------------
# Analysis plugins and dialogs: each one's ``Icon``
# ---------------------------------------------------------------------------

BASELINE: str = """
<path d="M3 17c3 0 3-10 6-10s3 10 6 10 3-6 6-6"/>
<path d="M3 19h18" stroke-dasharray="2 2"/>
"""

CALCULUS: str = """
<path d="M7 19c0-6 2-14 5-14"/>
<path d="M5 12h9"/>
<path d="M14 19h5"/>
"""

CHANGE: str = """
<path d="M3 17l4-2 3 1 3-5 3-1 5-6"/><path d="M3 21h18"/><circle cx="13" cy="11" r="1.6"/>
"""

CLUSTER: str = """
<circle cx="7" cy="8" r="2"/>
<circle cx="16.5" cy="7" r="2"/>
<circle cx="10" cy="16" r="2"/>
<circle cx="18" cy="15.5" r="2"/>
<path d="M8.8 9.5l5.9 4.8"/>
<path d="M15 8.3l-3.6 6.1"/>
<path d="M12 16h4"/>
"""

CONTROL_CHART: str = """
<path d="M3 8h18"/>
<path d="M3 16h18"/>
<path d="M3 12h18" stroke-dasharray="2 2"/>
<path d="M5 13l3-2 3 3 3-5 3 4 3-2"/>
"""

DECOMPOSITION: str = """
<circle cx="7" cy="7" r="2"/>
<circle cx="16" cy="6" r="2"/>
<circle cx="12" cy="13" r="2"/>
<circle cx="6" cy="17" r="2"/>
<circle cx="17" cy="17" r="2"/>
<path d="M12 13l-5-6M12 13l4-7M12 13l-6 4M12 13l5 4" stroke-dasharray="1 2"/>
"""

DIFFERENCES: str = """
<rect x="3" y="8" width="5" height="9" rx="1"/><rect x="10" y="4" width="5" height="9" rx="1"/>
<rect x="17" y="11" width="4" height="8" rx="1"/><path d="M2 21h20"/>
"""

DISCRIMINANT: str = """
<circle cx="6" cy="8" r="1.6"/><circle cx="8.5" cy="5" r="1.6"/><circle cx="5" cy="12.5" r="1.6"/>
<circle cx="17" cy="15" r="1.6"/><circle cx="19" cy="19" r="1.6"/><circle cx="15" cy="19.5" r="1.6"/>
<path d="M3 21L21 3"/>
"""

DISTRIBUTION: str = """
<path d="M4 20V14h3v6M8.5 20V8h3v12M13 20V5h3v15M17.5 20v-9h3v9"/><path d="M3 20h18"/>
"""

FACTOR_ANALYSIS: str = """
<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/>
<rect x="15" y="3" width="5" height="3.5" rx="0.8"/><rect x="15" y="10.2" width="5" height="3.5" rx="0.8"/>
<rect x="15" y="17.5" width="5" height="3.5" rx="0.8"/>
<path d="M8 6.5l7-1.5M8 7l7 4.5M8 17l7-4.5M8 17.5l7 1.5"/>
"""

FILTER: str = """
<path d="M3 12h4l2-7 4 14 2-7h6"/>
"""

FIT: str = """
<path d="M4 18.5h16"/>
<path d="M4.5 18V5"/>
<path d="M6.5 15.5c2.2-5.6 5.2-7.8 11-7.6"/>
<circle cx="7" cy="15" r="1.2"/>
<circle cx="11" cy="10.8" r="1.2"/>
<circle cx="16.5" cy="8" r="1.2"/>
"""

FIT_MODEL: str = """
<path d="M4 20V4"/><path d="M4 20h16"/>
<circle cx="8" cy="15" r="1"/><circle cx="11" cy="11" r="1"/><circle cx="15" cy="10" r="1"/><circle cx="18" cy="6" r="1"/>
<path d="M6 17L19 5"/>
"""

FIT_Y_BY_X: str = """
<path d="M4 4v16h16"/><circle cx="8" cy="15" r="1.2"/><circle cx="11" cy="12" r="1.2"/>
<circle cx="14" cy="11" r="1.2"/><circle cx="17" cy="7" r="1.2"/><path d="M6 17L19 6"/>
"""

FUNCTION: str = """
<path d="M4 20c4 0 4-16 8-16"/><path d="M12 4c4 0 4 16 8 16"/>
"""

GAGE: str = """
<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/><path d="M8 18h8"/>
"""

GEOMETRY: str = """
<rect x="3" y="9" width="10" height="10" rx="1"/>
<path d="M14.5 4.5l6.2 6.2-6.2 6.2-6.2-6.2z"/>
"""

GP_REGRESSION: str = """
<path d="M4 16c3-8 6-8 8 0s5 8 8 0" stroke-dasharray="2 2"/>
<path d="M4 12c3-6 6-6 8 0s5 6 8 0"/>
<path d="M4 8c3-4 6-4 8 0s5 4 8 0" stroke-dasharray="2 2"/>
"""

IMPACT: str = """
<rect x="3" y="4" width="18" height="3.2" rx="1"/><rect x="3" y="10.4" width="11" height="3.2" rx="1"/>
<rect x="3" y="16.8" width="5" height="3.2" rx="1"/>
"""

IN_CONTROL: str = """
<path d="M3 6h18" stroke-dasharray="2 2"/><path d="M3 18h18" stroke-dasharray="2 2"/>
<path d="M3 12l3-2 3 3 3-4 3 2 3-1 3 2"/>
"""

INTERPOLATE: str = """
<path d="M4 18.5h16"/>
<path d="M4.5 18V5"/>
<path d="M6.5 15.5l4.2-4.2 3.2 2.4 4.2-6.2"/>
<circle cx="6.5" cy="15.5" r="1"/>
<circle cx="10.7" cy="11.3" r="1"/>
<circle cx="13.9" cy="13.7" r="1"/>
<circle cx="18.1" cy="7.5" r="1"/>
"""

METHOD_COMPARISON: str = """
<path d="M4 20L20 4" stroke-dasharray="2 2"/><circle cx="7" cy="16" r="1.3"/><circle cx="11" cy="12.5" r="1.3"/>
<circle cx="14" cy="10" r="1.3"/><circle cx="17" cy="6.5" r="1.3"/><path d="M3 21h18M3 3v18"/>
"""

MULTIVARIATE: str = """
<rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="13" width="8" height="8" rx="1"/>
<circle cx="16" cy="6" r="1.2"/><circle cx="18" cy="8" r="1.2"/><circle cx="6" cy="17" r="1.2"/><circle cx="8" cy="15" r="1.2"/>
"""

NORMALITY: str = """
<path d="M2 19c3 0 4-12 10-12s7 12 10 12"/><path d="M2 21h20"/>
"""

OUTLIER: str = """
<circle cx="7" cy="8" r="1.3"/>
<circle cx="10.5" cy="11" r="1.3"/>
<circle cx="8.5" cy="15" r="1.3"/>
<circle cx="14" cy="9" r="1.3"/>
<circle cx="16" cy="14" r="1.3"/>
<circle cx="19" cy="5.5" r="1.5"/>
<path d="M17.8 6.7l-2 2"/>
"""

PARTITION: str = """
<circle cx="12" cy="4.5" r="2"/><circle cx="6" cy="12" r="2"/><circle cx="18" cy="12" r="2"/>
<circle cx="3.5" cy="19.5" r="1.6"/><circle cx="9" cy="19.5" r="1.6"/>
<path d="M10.6 6l-3.2 4.4M13.4 6l3.2 4.4M5 13.8l-1 4M7 13.8l1.4 4"/>
"""

PEAKS: str = """
<path d="M3 18l4-8 3 5 4-11 3 8 4-4"/>
<circle cx="14" cy="4" r="1.6"/>
"""

PLS: str = """
<path d="M3 18c2-9 4-12 6-6s3 6 5-2 3-6 7 1"/><path d="M3 21h18"/>
"""

PRINCIPAL_COMPONENTS: str = """
<circle cx="7" cy="16" r="1.3"/><circle cx="10" cy="13" r="1.3"/><circle cx="13" cy="11" r="1.3"/>
<circle cx="16" cy="8" r="1.3"/><circle cx="12" cy="14" r="1.3"/><circle cx="9" cy="10" r="1.3"/>
<path d="M4 20L20 4"/><path d="M8 6l8 12" stroke-dasharray="2 2"/>
"""

RANDOM_DATA: str = """
<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="8.5" cy="8.5" r="1.1"/>
<circle cx="15.5" cy="8.5" r="1.1"/><circle cx="12" cy="12" r="1.1"/><circle cx="8.5" cy="15.5" r="1.1"/>
<circle cx="15.5" cy="15.5" r="1.1"/>
"""

REGRESSION: str = """
<path d="M4 18c3-1 4-8 6-8s2 6 4 6 3-9 6-9"/>
<circle cx="6" cy="15" r="1"/>
<circle cx="12" cy="9" r="1"/>
<circle cx="16" cy="14" r="1"/>
"""

ROOTS: str = """
<path d="M3 12h18"/>
<path d="M3 19c4 0 5-14 9-14s5 10 9 10"/>
<circle cx="8.4" cy="12" r="1.8"/>
"""

SMOOTHING: str = """
<path d="M4 13c1.7-4 3.4 4 5.1 0s3.4-4 5.1 0 3.4 4 5.8-1"/>
<path d="M4 17c3.3-2.3 6.7-2.3 10 0 2 1.3 4 1.3 6 0"/>
"""

SPECTRAL: str = """
<path d="M4 18.5h16"/>
<path d="M4.5 18V5"/>
<path d="M7 16v-3"/>
<path d="M10 16V8"/>
<path d="M13 16v-6"/>
<path d="M16 16V6"/>
<path d="M19 16v-4"/>
"""

STATISTICS: str = """
<path d="M5 19h14"/>
<path d="M7 16v-5"/>
<path d="M12 16V7"/>
<path d="M17 16v-8"/>
<path d="M6 5h12"/>
"""

TIME_SERIES: str = """
<path d="M3 16l3-4 3 2 3-6 3 3"/><path d="M15 11l3-2 3 1" stroke-dasharray="2 2"/>
<path d="M15 8l6-2M15 14l6 2" stroke-dasharray="1 2"/><path d="M3 21h18"/>
"""

TRANSFORM: str = """
<path d="M4 15c4-8 5 8 9 0s5-8 7 0" transform="translate(0 -2)"/>
<path d="M4 19h16" opacity="0.4"/>
"""

VECTOR_FIELD: str = """
<path d="M4 18l5-5"/><path d="M9 13l-1 3"/><path d="M9 13l-3 1"/><path d="M12 8l6-3"/><path d="M18 5l-3 0"/>
<path d="M18 5l-1 3"/><path d="M14 18l5-1"/>
"""

WAFER_MAP: str = """
<path d="M12 3a9 9 0 1 0 1.2 .08L12 4.6z"/><path d="M7 8h10M7 12h10M7 16h10M9 6v12M12 4.6v14.4M15 6v12"/>
"""

CREATE_CHART: str = """
<path d="M4 19.5h16"/>
<path d="M4.5 19V5"/>
<path d="M7 15l3.2-3.2 2.5 2.5L18 8"/>
<path d="M15.5 8H18v2.5"/>
"""

ANALYSIS_DEFAULT: str = """
<rect x="5" y="5" width="14" height="14" rx="3"/>
<path d="M8.5 12h7"/>
<path d="M12 8.5v7"/>
"""
