"""The tests that take more than about a second: the normal run leaves them out.

``pytest dev/tests`` runs the quick ones, ``pytest dev/tests --all`` every one; a file
named on the command line runs whole either way. A line is a file, or ``file::test``
(every case of it), or ``file::test[case]``. Times are from the run of 2026-11-15.
"""

SLOW_TESTS = frozenset(
    {
        "test_demo_projects.py",  # 79 s: every demo project is built and opened
        "test_left_panel_insets.py",  # 16 s: the whole window, per style
        "test_symbolic_calculus.py::test_the_formulas",  # 8 s
        "test_reading_guide.py::test_a_report_explains_its_own_numbers_unless_switched_off"
        "[time_series_dialog-TimeSeriesDialog-shop-casting11-AIC]",  # 7 s
        "test_time_series.py::test_ok_with_an_input_draws_the_cross_correlation",  # 7 s
        "test_time_series.py::test_a_model_that_fits_is_not_one_step_behind",  # 5 s
        "test_time_series.py::test_the_order_chosen_by_aic_is_seasonal_and_differenced",  # 4 s
        "test_time_series.py::test_ok_writes_the_tables_and_draws_the_series_its_correlations_and_parts",
        "test_publication_export.py::test_the_report_dialog_writes_a_pdf",  # 5 s
        "test_publication_export.py::test_the_report_has_every_figure_and_no_sql",  # 5 s
        "test_render_all_renderers.py::test_renderer_draws_and_saves",  # 5 s
        "test_machine_translation.py::test_deepl_refusals_are_named",  # 4 s
        "test_machine_translation.py::test_the_dialog_fills_only_empty_cells",
        "test_tab_switch_redraw.py::test_switching_tabs_redraws_at_the_canvas_size",  # 4 s
        "test_installer.py::test_a_venv_is_created_kept_and_recreated",  # 4 s
        "test_installer.py::test_the_check_names_every_library_an_empty_venv_lacks",
        "test_installer.py::test_a_venv_that_already_existed_is_not_deleted_by_a_failed_install",
        "test_installer.py::test_a_failed_install_leaves_no_half_made_venv",
        "test_chart_click_parts.py::test_flash_highlights_an_axis_or_a_series_for_a_moment",  # 3 s
        "test_project_info.py::test_a_figure_keeps_notes_and_its_dates_follow_its_changes",
        "test_animation.py::test_the_animation_page_stores_the_settings_and_plays_the_chart",
        "test_style_editor_params.py::test_every_rcparam_toggles_or_opens_an_editor",
        "test_undo_per_element.py::"
        "test_each_element_and_property_is_its_own_step_and_a_colour_comes_back_live",
        "test_function_sql.py::test_opening_a_project_that_draws_untrusted_functions_asks_once",
        "test_axis_stepper.py::test_the_arrows_change_the_axis_everywhere",
        "test_impact.py::test_a_categorical_result_and_no_impact",
        "test_impact.py::test_ok_writes_the_ranking_and_draws_a_pareto",
        "test_function_editor.py::test_series_properties_edit_a_function_series",
        "test_chart_panel_redraws.py::test_a_reload_redraws_and_a_hidden_panel_waits",
        "test_click_selects_properties.py::test_clicks_select_the_figure_the_axis_and_the_series",
        "test_ui_small.py::test_a_new_plot_becomes_the_current_tab",
        "test_analysis_api.py::test_an_analysis_runs_and_hands_back_its_report",
        "test_multi_descriptor_render.py::test_render_multi_descriptor_multiple_figures",
        "test_column_info_button.py::test_the_button_opens_the_first_column_when_no_cell_is_current",
        "test_geometry_hidden_rows.py::"
        "test_a_rotated_hide_filtered_series_is_written_as_valid_sql_and_drawn",
        "test_developer_launchers.py::test_macos_app_has_executable_icon_and_plist",
    }
)
