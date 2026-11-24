"""New Chart: the series' query is in a box of its own under the Series card, closed until opened."""
from __future__ import annotations

import pandas as pd

from app.dialogs.create_chart_dialog import NewPlotTabDialog


def test_the_query_is_in_its_own_closed_box_and_still_written(qapp, repo) -> None:
    repo.import_dataframe(pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]}), table_name="t", normalize_columns=False)
    dialog = NewPlotTabDialog(repo, current_table="t")
    try:
        dialog.show()
        qapp.processEvents()
        card = dialog._query_card
        assert card.collapsed and not dialog._edit_sql.isVisible()
        assert dialog._edit_sql.parentWidget() is card.card  # not a row of the Series form any more
        assert "FROM" in dialog._edit_sql.toPlainText()  # written from the source all the same
        card.disclosure.click()
        qapp.processEvents()
        assert not card.collapsed and dialog._edit_sql.isVisible()
        column = dialog.column(1).layout()
        assert column.indexOf(card) > column.indexOf(dialog._edit_series_name.parentWidget().parentWidget().parentWidget())
    finally:
        dialog.close()
