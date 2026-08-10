"""The renderer's arithmetic, and the two bugs that only a rendered page revealed.

The report is HTML, so most of it is checked by looking at it. What is worth testing
is the geometry underneath: a mark is positioned by dividing a value by an axis
maximum, and if that maximum can be smaller than the data the mark leaves the plot.
That happened, and it is the first test here.
"""

import json

import pytest
from qc_report import (
    build,
    column_path,
    compact,
    heat_class,
    nice_ticks,
    thousands,
)


class TestNiceTicks:
    def test_last_tick_covers_the_data(self):
        """The bug this exists for.

        Marks are scaled by ticks[-1]. With a peak of 5400 an earlier version
        returned [0, 2500, 5000], so the tallest column computed to 202px inside a
        150px plot, escaped the SVG and drew over the paragraph above the chart.
        """
        for peak in (1, 7, 42, 99, 100, 101, 5400, 5401, 12_688, 142_493, 246_208_410):
            ticks = nice_ticks(peak)
            assert ticks[-1] >= peak, f"peak {peak} exceeds last tick {ticks[-1]}"

    def test_ticks_are_round_numbers(self):
        assert nice_ticks(5400) == [0, 2000, 4000, 6000]
        assert nice_ticks(100) == [0, 25, 50, 75, 100]

    def test_starts_at_zero(self):
        """Bars grow from a single baseline, so the axis has to start there."""
        assert nice_ticks(3738)[0] == 0

    def test_evenly_spaced(self):
        ticks = nice_ticks(9451)
        gaps = {round(b - a, 6) for a, b in zip(ticks, ticks[1:], strict=False)}
        assert len(gaps) == 1

    def test_zero_and_negative(self):
        assert nice_ticks(0) == [0.0]
        assert nice_ticks(-5) == [0.0]

    def test_fractional_upper(self):
        ticks = nice_ticks(4.3)  # headroom stops, the real case
        assert ticks[-1] >= 4.3


class TestCompact:
    def test_thousands_separated_below_ten_thousand(self):
        assert compact(1284) == "1,284"

    def test_abbreviated_above_ten_thousand(self):
        assert compact(142493) == "142.5K"

    def test_millions(self):
        assert compact(246_208_410) == "246.2M"

    def test_fractional_kept(self):
        assert compact(4.3) == "4.3"

    def test_integral_float_has_no_decimal(self):
        assert compact(10.0) == "10"


class TestThousands:
    def test_rounds_and_separates(self):
        assert thousands(3738.1) == "3,738"
        assert thousands(142493) == "142,493"


class TestHeatClass:
    def test_spans_all_five_steps(self):
        assert heat_class(0, 100) == 0
        assert heat_class(100, 100) == 4

    def test_maximum_does_not_overflow_the_ramp(self):
        """int(value/upper*5) is 5 at the maximum, which would index past the ramp."""
        for upper in (1, 7, 3343):
            assert heat_class(upper, upper) == 4

    def test_real_grid(self):
        """Boundaries on the published run: max 3343 over five steps."""
        assert heat_class(214, 3343) == 0
        assert heat_class(3343, 3343) == 4

    def test_zero_upper_is_safe(self):
        assert heat_class(0, 0) == 0


class TestColumnPath:
    def test_zero_height_draws_nothing(self):
        """An empty bin must produce no mark rather than a sliver at the baseline."""
        assert column_path(0, 0, 10, 0) == ""

    def test_rounding_cannot_exceed_the_mark(self):
        """A 1px column with a 4px corner radius would invert the path."""
        assert column_path(0, 0, 1, 1) != ""


def minimal_metrics():
    return {
        "sample": "s",
        "store": "/data/runs/s.zarr",
        "image_element": "s",
        "image": {"shape_cyx": [2, 8, 8], "dtype": "uint16", "n_pyramid_levels": 1},
        "cells": {
            "n_cells": 4,
            "min": 4.0,
            "max": 1000.0,
            "mean": 488.5,
            "min_cell_area": 10.0,
            "n_below_min_cell_area": 1,
            "fraction_below_min_cell_area": 0.25,
            "p1": 4.0,
            "p25": 40.0,
            "p50": 475.0,
            "p75": 925.0,
            "p99": 998.0,
            "p99_9": 1000.0,
            "p99_99": 1000.0,
            "histogram": [1, 0, 2],
            "histogram_upper": 998.0,
            "histogram_bin_width": 332.7,
            "n_above_histogram_upper": 1,
        },
        "channels": {
            "n_channels": 2,
            "table_names": ["a", "b"],
            "image_names": ["a", "b"],
            "table_matches_image": True,
            "per_channel": {
                "a": {
                    "min": 0,
                    "max": 300,
                    "mean": 5.0,
                    "n_pixels": 64,
                    "dtype_ceiling": 65535,
                    "fraction_at_dtype_ceiling": 0.0,
                    "fraction_zero": 0.97,
                    "effective_bit_depth": 9,
                    "headroom_stops": 7.77,
                    "p1": 0,
                    "p25": 0,
                    "p50": 0,
                    "p75": 0,
                    "p99": 100,
                    "p99_9": 300,
                    "p99_99": 300,
                    "histogram": [62, 1, 1],
                    "histogram_upper": 300,
                    "histogram_bin_width": 2.35,
                },
                "b": {
                    "min": 7,
                    "max": 7,
                    "mean": 7.0,
                    "n_pixels": 64,
                    "dtype_ceiling": 65535,
                    "fraction_at_dtype_ceiling": 0.0,
                    "fraction_zero": 0.0,
                    "effective_bit_depth": 8,
                    "headroom_stops": 13.0,
                    "p1": 7,
                    "p25": 7,
                    "p50": 7,
                    "p75": 7,
                    "p99": 7,
                    "p99_9": 7,
                    "p99_99": 7,
                    "histogram": [64],
                    "histogram_upper": 7,
                    "histogram_bin_width": 0.06,
                },
            },
        },
        "cycle_ratio": {
            "available": True,
            "nuclear_pattern": "DAPI",
            "first_channel": "a",
            "last_channel": "b",
            "first_cycle": 1,
            "last_cycle": 3,
            "n_cells": 4,
            "n_usable": 3,
            "n_undefined": 1,
            "median_log2_ratio": -0.32,
            "mean_log2_ratio": -0.41,
            "p1_log2_ratio": -2.1,
            "p99_log2_ratio": 0.8,
            "n_below_half": 1,
            "fraction_below_half": 0.25,
            "histogram": [0, 1, 2, 0],
            "histogram_min": -4.0,
            "histogram_max": 4.0,
            "histogram_bin_width": 2.0,
            "n_below_histogram_min": 0,
            "n_above_histogram_max": 0,
        },
        "patches": {
            "n_patches": 2,
            "n_empty_patches": 1,
            "fraction_empty_patches": 0.5,
            "cells_per_patch_min": 0,
            "cells_per_patch_max": 4,
            "cells_per_patch_mean": 2.0,
            "cells_per_patch_median": 2.0,
            "centroid_assignments": 4,
            "n_cells": 4,
            "cells_per_patch": [4, 0],
            "ilocs": [[0, 0], [1, 0]],
        },
    }


class TestBuild:
    def test_renders_a_whole_page(self):
        page = build(minimal_metrics())
        assert page.startswith("<!DOCTYPE html>")
        assert page.rstrip().endswith("</html>")

    def test_entities_are_not_double_escaped(self):
        """The bug a rendered page showed immediately.

        Values pass through html.escape, which turns "&" into "&amp;" -- so writing
        "px&sup2;" in a value produced the literal text "px&sup2;" on the page.
        Literal Unicode is used instead, and this catches a regression to entities.
        """
        page = build(minimal_metrics())
        assert "&amp;" not in page
        assert "px²" in page

    def test_no_external_references(self):
        """It has to open on a cluster with no network. No CDN, no remote font."""
        page = build(minimal_metrics())
        for pattern in ("http://", "https://", "src=", "@import"):
            assert pattern not in page, f"found {pattern!r}"

    def test_every_chart_has_a_table(self):
        """Nothing may be readable only by looking at a colour."""
        page = build(minimal_metrics())
        assert page.count("<details>") >= 4

    def test_empty_patch_is_marked_not_shaded(self):
        """A zero-cell patch is a finding, so it is not the bottom of the ramp."""
        page = build(minimal_metrics())
        assert "no cells" in page

    def test_marker_sheet_mismatch_shown(self):
        m = minimal_metrics()
        m["channels"]["matches_marker_sheet"] = False
        m["channels"]["marker_sheet_names"] = ["x", "y"]
        assert "marker sheet" in build(m).lower()

    def test_cycle_ratio_section_present(self):
        page = build(minimal_metrics())
        assert "Nuclear stain across cycles" in page
        assert "no change" in page

    def test_cycle_ratio_absence_is_stated_not_hidden(self):
        """An omitted section reads as "nothing wrong", which is not the same thing."""
        m = minimal_metrics()
        m["cycle_ratio"] = {"available": False, "reason": "only one cycle"}
        page = build(m)
        assert "Nuclear stain across cycles" in page
        assert "only one cycle" in page

    def test_before_after_uses_a_dumbbell_with_a_legend(self):
        """Two series means a legend is mandatory."""
        m = minimal_metrics()
        for name in m["channels"]["per_channel"]:
            m["channels"]["per_channel"][name]["before"] = dict(m["channels"]["per_channel"][name])
        page = build(m)
        assert "before subtraction" in page
        assert "after subtraction" in page

    def test_headroom_is_gone(self):
        """Removed on request: it was not useful for judging a run."""
        page = build(minimal_metrics())
        assert "Headroom" not in page
        assert "Bits used" not in page

    def test_mean_and_median_are_columns(self):
        page = build(minimal_metrics())
        assert "<th>Mean</th>" in page
        assert "<th>Median</th>" in page

    def test_untiled_run_omits_the_patch_section(self):
        m = minimal_metrics()
        m["patches"] = None
        page = build(m)
        assert "Cells per patch" not in page

    def test_survives_a_single_channel(self):
        m = minimal_metrics()
        del m["channels"]["per_channel"]["b"]
        m["channels"]["n_channels"] = 1
        assert build(m).startswith("<!DOCTYPE html>")

    def test_json_round_trip(self):
        """The renderer's only input is the file on disk, so it must survive it."""
        assert build(json.loads(json.dumps(minimal_metrics()))).startswith("<!DOCTYPE")

    def test_hero_number_is_present_unabbreviated(self):
        """The one number the page leads with is exact, not compacted."""
        m = minimal_metrics()
        m["cells"]["n_cells"] = 142493
        assert "142,493" in build(m)


class TestNoMarkEscapesItsPlot:
    def test_column_heights_stay_within_the_plot(self):
        """Reconstructs the overflow bug from the renderer's own numbers.

        Any counts whose peak lands just above a round tick used to overflow. This
        asserts the invariant directly: value / ticks[-1] never exceeds 1.
        """
        for peak in (5400, 101, 2501, 12_688, 999_999):
            assert peak / nice_ticks(peak)[-1] <= 1.0

    def test_headroom_bars_stay_within_the_plot(self):
        for value in (4.3, 1.77, 13.0, 0.01):
            assert value / nice_ticks(value)[-1] <= 1.0


@pytest.mark.parametrize("n_cells", [0, 1, 142493])
def test_cell_counts_render(n_cells):
    m = minimal_metrics()
    m["cells"]["n_cells"] = n_cells
    assert build(m).startswith("<!DOCTYPE html>")
