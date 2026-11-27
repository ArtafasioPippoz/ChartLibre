"""Domain colouring: the safe f(z) evaluator, the colours, and the pack's renderer on both sources."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from matplotlib.colors import rgb_to_hsv  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from app.analysis import complex_plane as cp  # noqa: E402
from app.data.series_frame import SeriesFrame  # noqa: E402
from app.plugin_api.charts.base import SeriesData  # noqa: E402

PACK_CHART = Path(__file__).resolve().parents[1] / "packs" / "complex" / "charts" / "domain_colouring.py"


def _renderer():
    spec = importlib.util.spec_from_file_location("domain_colouring_under_test", PACK_CHART)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DomainColouringAxisRenderer()


def _series(frame: pd.DataFrame) -> SeriesData:
    return SeriesData(name="f", df=SeriesFrame({name: frame[name].tolist() for name in frame.columns}), style={})


def test_the_evaluator_reads_arithmetic_and_the_listed_functions() -> None:
    f = cp.compile_function("z^2 + 2i*exp(z) - sqrt(pi)")
    z = np.array([0.5 - 1j, 2 + 0j])
    assert np.allclose(f(z), z**2 + 2j * np.exp(z) - np.sqrt(np.pi))
    assert np.allclose(cp.compile_function("3")(z), 3)  # a constant still gives one value per point


@pytest.mark.parametrize("text", ["__import__('os')", "z.real", "open('x')", "[z][0]", "y + 1", "exp(z, out=z)"])
def test_the_evaluator_refuses_everything_else(text: str) -> None:
    with pytest.raises(ValueError):
        cp.compile_function(text)


def test_hue_is_the_argument_and_lightness_the_modulus() -> None:
    hsv = rgb_to_hsv(cp.domain_colours(np.array([1, 1j, -1, 1e-6, 1e6]), cp.MODULUS_SMOOTH))
    assert np.allclose(hsv[:3, 0], [0.0, 0.25, 0.5], atol=1e-6)
    assert np.allclose(hsv[:3, 1:], 1.0)          # |w| = 1: full colour
    assert hsv[3, 2] < 0.01 and hsv[4, 1] < 0.01  # near 0 black, near infinity white


def test_a_pole_is_white_and_a_nan_grey() -> None:
    rgb = cp.domain_colours(np.array([complex(np.inf, 0), complex(np.nan, np.nan)]))
    assert np.allclose(rgb[0], 1.0) and np.allclose(rgb[1], 0.5)


def test_the_function_is_evaluated_again_after_a_zoom() -> None:
    ax = Figure().add_subplot()
    frame = pd.DataFrame({"x": [-2.0, 2.0], "y": [-1.0, 1.0]})
    _renderer().render_axis(ax, [_series(frame)], {"function": "z", "resolution": 80})
    image = ax.images[0]
    assert image.get_array().shape == (40, 80, 3)
    ax.set_xlim(0.5, 1.5)
    ax.set_ylim(-0.25, 0.25)
    assert tuple(image.get_extent()) == (0.5, 1.5, -0.25, 0.25)
    # Every point now has Re z > 0, so no hue is near cyan (arg = pi).
    hue = rgb_to_hsv(np.asarray(image.get_array()))[..., 0]
    assert np.all(np.abs(hue - 0.5) > 0.2)


def test_re_and_im_columns_are_drawn_as_given() -> None:
    xs, ys = np.meshgrid(np.linspace(-1, 1, 5), np.linspace(-1, 1, 3))
    w = (xs + 1j * ys) ** 2
    frame = pd.DataFrame({"x": xs.ravel(), "y": ys.ravel(), "re": w.real.ravel(), "im": w.imag.ravel()})
    ax = Figure().add_subplot()
    _renderer().render_axis(ax, [_series(frame)], {"function": "not used"})
    drawn = np.asarray(ax.images[0].get_array())
    assert drawn.shape == (3, 5, 3)
    assert np.allclose(drawn, cp.domain_colours(w))


def test_equal_scale_widens_the_view_and_the_function_follows() -> None:
    fig = Figure(figsize=(8, 4))
    ax = fig.add_subplot()
    frame = pd.DataFrame({"x": [-1.0, 1.0], "y": [-1.0, 1.0]})
    _renderer().render_axis(ax, [_series(frame)], {"function": "z", "resolution": 60})
    fig.canvas.draw() if hasattr(fig.canvas, "draw") else None
    ax.apply_aspect()
    x0, x1 = sorted(ax.get_xlim())
    assert x1 - x0 > 2.5  # a wide axes shows more of Re than of Im
    assert tuple(ax.images[0].get_extent())[:2] == (x0, x1)


def _path_renderer():
    spec = importlib.util.spec_from_file_location("complex_path_under_test", PACK_CHART.with_name("complex_path.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ComplexPathAxisRenderer()


def _circle(n: int = 101) -> pd.DataFrame:
    t = np.linspace(0, 1, n)
    return pd.DataFrame({"x": np.cos(2 * np.pi * t), "y": np.sin(2 * np.pi * t), "t": t})


def test_a_path_is_drawn_in_order_of_t_and_coloured_by_it() -> None:
    ax = Figure().add_subplot()
    frame = _circle().sample(frac=1.0, random_state=3)  # rows shuffled: t puts them back in order
    _path_renderer().render_axis(ax, [_series(frame)], {"arrows": 3})
    collection = ax.collections[0]
    segments = collection.get_segments()
    assert len(segments) == 100
    assert np.allclose(segments[0][0], [1, 0]) and np.allclose(segments[-1][1], [1, 0], atol=1e-9)
    assert np.all(np.diff(collection.get_array()) > 0)
    assert ax.get_aspect() == 1.0


def test_the_image_of_a_circle_under_z_cubed_winds_three_times() -> None:
    ax = Figure().add_subplot()
    _path_renderer().render_axis(ax, [_series(_circle(301))], {"function": "z^3", "arrows": 0})
    points = np.array([segment[0] for segment in ax.collections[0].get_segments()])
    turns = np.sum(np.diff(np.unwrap(np.angle(points[:, 0] + 1j * points[:, 1])))) / (2 * np.pi)
    assert round(turns) == 3


def test_a_pole_on_the_path_breaks_it_instead_of_joining_across_infinity() -> None:
    ax = Figure().add_subplot()
    frame = pd.DataFrame({"x": [-1.0, -0.5, 0.0, 0.5, 1.0], "y": [0.0] * 5})
    _path_renderer().render_axis(ax, [_series(frame)], {"function": "1/z", "arrows": 0, "mark_ends": False})
    assert len(ax.collections[0].get_segments()) == 2
