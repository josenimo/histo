"""QC metric arithmetic.

The numbers in the expectations come from the published WSI run in scratch/output
wherever a real value was available, so a regression shows up as a disagreement
with something that actually happened rather than with a number someone invented.
"""

import numpy as np
import pytest
from qc_metrics import (
    _pct_key,
    area_metrics,
    cycle_ratio_metrics,
    nuclear_cycle_pair,
    read_marker_cycles,
    cells_per_patch,
    channel_metrics,
    effective_bit_depth,
    patch_metrics,
    percentiles_from_histogram,
)


class TestPercentilesFromHistogram:
    def test_uniform(self):
        """Ten values 0..9, one pixel each.

        p50 is 4, not 5: it is the lowest value whose cumulative count reaches half
        the pixels, which is the "lower" convention numpy calls method="lower".
        """
        hist = np.ones(10, dtype=np.int64)
        out = percentiles_from_histogram(hist, (50.0,))
        assert out["p50"] == 4.0
        assert out["p50"] == np.percentile(np.arange(10), 50, method="lower")

    def test_exact_not_interpolated(self):
        """Every reported number must be a value that occurs in the image.

        numpy's default percentile would interpolate to 0.5 here, which is a value
        no pixel has. For QC that matters: a reported intensity should be findable.
        """
        hist = np.array([1, 0, 0, 0, 1], dtype=np.int64)  # one pixel at 0, one at 4
        out = percentiles_from_histogram(hist, (50.0,))
        assert out["p50"] in (0.0, 4.0)
        assert out["p50"] == float(int(out["p50"]))

    def test_all_mass_in_one_bin(self):
        hist = np.zeros(100, dtype=np.int64)
        hist[42] = 1000
        out = percentiles_from_histogram(hist, (1.0, 50.0, 99.9))
        assert out["p1"] == out["p50"] == out["p99_9"] == 42.0

    def test_tail_separates_from_p99(self):
        """The reason p99.99 is reported at all.

        Two hundredths of a percent of the pixels pinned to 1000 does not move p99
        at all, which is the failure mode that makes a p99-only saturation check
        useless. p99.99 sees them, because the tail is larger than the 0.01% it
        excludes.
        """
        hist = np.zeros(1001, dtype=np.int64)
        hist[100] = 999_800
        hist[1000] = 200
        out = percentiles_from_histogram(hist, (99.0, 99.99))
        assert out["p99"] == 100.0
        assert out["p99_99"] == 1000.0

    def test_empty_refused(self):
        with pytest.raises(ValueError, match="empty histogram"):
            percentiles_from_histogram(np.zeros(10, dtype=np.int64))


class TestPctKey:
    def test_integer_percentile(self):
        assert _pct_key(50.0) == "p50"

    def test_fractional_percentile(self):
        assert _pct_key(99.9) == "p99_9"
        assert _pct_key(99.99) == "p99_99"


class TestEffectiveBitDepth:
    def test_full_uint16(self):
        assert effective_bit_depth(65535) == 16

    def test_twelve_bit_in_uint16(self):
        """A 12-bit detector writing into uint16 leaves four bits always zero."""
        assert effective_bit_depth(4095) == 12

    def test_real_channel_maximum(self):
        """CD38 on the published run peaked at 3337, so 12 bits of 16 used."""
        assert effective_bit_depth(3337) == 12

    def test_floor_at_eight(self):
        """A nearly empty channel is not a 4-bit detector; do not imply it is."""
        assert effective_bit_depth(3) == 8

    def test_all_zero(self):
        assert effective_bit_depth(0) == 0

    def test_negative_refused(self):
        with pytest.raises(ValueError, match="non-negative"):
            effective_bit_depth(-1)


class TestChannelMetrics:
    def test_unsaturated_channel_reports_headroom(self):
        """The published run's shape: nothing at the ceiling, several stops unused."""
        hist = np.zeros(65536, dtype=np.int64)
        hist[0] = 100
        hist[4095] = 100
        m = channel_metrics(hist, dtype_max=65535)
        assert m["max"] == 4095
        assert m["fraction_at_dtype_ceiling"] == 0.0
        assert m["effective_bit_depth"] == 12
        assert m["headroom_stops"] == 4.0

    def test_genuine_saturation_is_caught(self):
        hist = np.zeros(65536, dtype=np.int64)
        hist[1000] = 990
        hist[65535] = 10
        m = channel_metrics(hist, dtype_max=65535)
        assert m["fraction_at_dtype_ceiling"] == pytest.approx(0.01)
        assert m["headroom_stops"] == 0.0

    def test_fraction_zero_catches_backsub_clipping(self):
        """backsub clips at zero, and a mostly-zero channel has lost its signal.

        CD68 on the published run came out 33% zero while the unsubtracted
        background channels sat at 0.45%.
        """
        hist = np.zeros(65536, dtype=np.int64)
        hist[0] = 333
        hist[500] = 667
        m = channel_metrics(hist, dtype_max=65535)
        assert m["fraction_zero"] == pytest.approx(0.333)

    def test_mean_is_intensity_weighted(self):
        hist = np.zeros(65536, dtype=np.int64)
        hist[10] = 3
        hist[20] = 1
        m = channel_metrics(hist, dtype_max=65535)
        assert m["mean"] == pytest.approx((10 * 3 + 20) / 4)
        assert m["n_pixels"] == 4

    def test_min_is_lowest_present_not_zero(self):
        hist = np.zeros(65536, dtype=np.int64)
        hist[7] = 5
        m = channel_metrics(hist, dtype_max=65535)
        assert m["min"] == 7

    def test_empty_channel_refused(self):
        with pytest.raises(ValueError, match="no pixels"):
            channel_metrics(np.zeros(65536, dtype=np.int64), dtype_max=65535)


class TestAreaMetrics:
    def test_degenerate_cells_counted(self):
        """4.3 px squared against a 1009 median is debris, and it really happened."""
        areas = np.array([4.3, 8.0, 1009.0, 1500.0])
        m = area_metrics(areas, min_cell_area=10.0)
        assert m["n_cells"] == 4
        assert m["n_below_min_cell_area"] == 2
        assert m["fraction_below_min_cell_area"] == 0.5
        assert m["min"] == pytest.approx(4.3)

    def test_threshold_is_strict(self):
        """A cell exactly at the threshold is kept, so the bound is documented."""
        m = area_metrics(np.array([10.0]), min_cell_area=10.0)
        assert m["n_below_min_cell_area"] == 0

    def test_threshold_echoed_back(self):
        """The JSON has to say which threshold produced the count."""
        m = area_metrics(np.array([100.0]), min_cell_area=42.0)
        assert m["min_cell_area"] == 42.0

    def test_no_cells_refused(self):
        with pytest.raises(ValueError, match="no cells"):
            area_metrics(np.array([]), min_cell_area=10.0)


class TestCellsPerPatch:
    def test_counts_centroids_in_bbox(self):
        centroids = np.array([[10.0, 10.0], [500.0, 500.0], [1500.0, 10.0]])
        bboxes = np.array([[0.0, 0.0, 1000.0, 1000.0], [1000.0, 0.0, 2000.0, 1000.0]])
        assert list(cells_per_patch(centroids, bboxes)) == [2, 1]

    def test_empty_patch_is_zero_not_missing(self):
        """A patch that produced nothing is the metric's whole point."""
        centroids = np.array([[10.0, 10.0]])
        bboxes = np.array([[0.0, 0.0, 100.0, 100.0], [1000.0, 1000.0, 1100.0, 1100.0]])
        assert list(cells_per_patch(centroids, bboxes)) == [1, 0]

    def test_overlap_double_counts_deliberately(self):
        """Patches overlap by patch_overlap_pixel, so the counts sum past the total.

        The published run assigned 151076 centroids across 72 patches for 142493
        cells. Hiding that would mean silently picking a winner per cell.
        """
        centroids = np.array([[1975.0, 10.0]])
        bboxes = np.array([[0.0, 0.0, 2000.0, 2000.0], [1950.0, 0.0, 3950.0, 2000.0]])
        assert list(cells_per_patch(centroids, bboxes)) == [1, 1]

    def test_upper_edge_is_half_open(self):
        """A centroid on a shared edge lands in one patch, not both."""
        centroids = np.array([[1000.0, 10.0]])
        bboxes = np.array([[0.0, 0.0, 1000.0, 1000.0], [1000.0, 0.0, 2000.0, 1000.0]])
        assert list(cells_per_patch(centroids, bboxes)) == [0, 1]

    def test_wrong_centroid_shape_refused(self):
        with pytest.raises(ValueError, match=r"centroids must be \(n, 2\)"):
            cells_per_patch(np.array([1.0, 2.0, 3.0]), np.array([[0.0, 0.0, 1.0, 1.0]]))

    def test_wrong_bbox_shape_refused(self):
        with pytest.raises(ValueError, match=r"bboxes must be \(n, 4\)"):
            cells_per_patch(np.array([[1.0, 2.0]]), np.array([[0.0, 0.0]]))


class TestPatchMetrics:
    def test_empty_patches_reported(self):
        m = patch_metrics(np.array([0, 5, 10]), n_cells=15)
        assert m["n_patches"] == 3
        assert m["n_empty_patches"] == 1
        assert m["fraction_empty_patches"] == pytest.approx(1 / 3)

    def test_overlap_excess_is_visible(self):
        """centroid_assignments past n_cells is the overlap, not a counting bug."""
        m = patch_metrics(np.array([10, 10]), n_cells=15)
        assert m["centroid_assignments"] == 20
        assert m["n_cells"] == 15

    def test_untiled_run_has_no_patches(self):
        assert patch_metrics(np.array([], dtype=np.int64), n_cells=0) == {"n_patches": 0}


class TestReadMarkerCycles:
    def test_parses_cycle_membership(self, tmp_path):
        p = tmp_path / "m.csv"
        p.write_text("channel_number,cycle_number,marker_name\n1,1,DAPI_bg\n2,2,CD3e\n3,2,DAPI_5\n")
        rows = read_marker_cycles(p)
        assert [r["cycle_number"] for r in rows] == [1, 2, 2]
        assert [r["marker_name"] for r in rows] == ["DAPI_bg", "CD3e", "DAPI_5"]

    def test_sorted_by_channel_number(self, tmp_path):
        """File order is not trusted, the same rule the name parser follows."""
        p = tmp_path / "m.csv"
        p.write_text("channel_number,cycle_number,marker_name\n3,2,C\n1,1,A\n2,1,B\n")
        assert [r["marker_name"] for r in read_marker_cycles(p)] == ["A", "B", "C"]

    def test_missing_cycle_column_refused(self, tmp_path):
        p = tmp_path / "m.csv"
        p.write_text("channel_number,marker_name\n1,A\n")
        with pytest.raises(ValueError, match="no 'cycle_number' column"):
            read_marker_cycles(p)


class TestNuclearCyclePair:
    def rows(self):
        """The published run's sheet: DAPI in all three cycles."""
        return [
            {"channel_number": 5, "cycle_number": 1, "marker_name": "DAPI_bg"},
            {"channel_number": 7, "cycle_number": 2, "marker_name": "CD3e"},
            {"channel_number": 10, "cycle_number": 2, "marker_name": "DAPI_5"},
            {"channel_number": 15, "cycle_number": 3, "marker_name": "DAPI_6"},
        ]

    def test_first_and_last_cycle(self):
        assert nuclear_cycle_pair(self.rows()) == ("DAPI_bg", "DAPI_6")

    def test_skips_the_middle_cycle(self):
        """Only the two ends are compared; DAPI_5 is cycle 2 and not an endpoint."""
        assert "DAPI_5" not in nuclear_cycle_pair(self.rows())

    def test_case_insensitive(self):
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "dapi"},
            {"channel_number": 2, "cycle_number": 2, "marker_name": "Dapi2"},
        ]
        assert nuclear_cycle_pair(rows) == ("dapi", "Dapi2")

    def test_single_cycle_has_nothing_to_compare(self):
        rows = [{"channel_number": 1, "cycle_number": 1, "marker_name": "DAPI"}]
        assert nuclear_cycle_pair(rows) is None

    def test_no_nuclear_channel_returns_none(self):
        """Returns None rather than guessing a channel, since the sheet has no flag."""
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "CD3e"},
            {"channel_number": 2, "cycle_number": 2, "marker_name": "CD8"},
        ]
        assert nuclear_cycle_pair(rows) is None

    def test_pattern_is_configurable(self):
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "Hoechst_1"},
            {"channel_number": 2, "cycle_number": 2, "marker_name": "Hoechst_2"},
        ]
        assert nuclear_cycle_pair(rows, pattern="hoechst") == ("Hoechst_1", "Hoechst_2")


class TestCycleRatioMetrics:
    def test_no_change_centres_on_zero(self):
        first = np.array([100.0, 200.0, 300.0])
        m = cycle_ratio_metrics(first, first.copy())
        assert m["median_log2_ratio"] == 0.0
        assert m["n_below_half"] == 0

    def test_halving_is_minus_one(self):
        """log2 so that half and double sit equidistant from no change."""
        m = cycle_ratio_metrics(np.array([100.0]), np.array([50.0]))
        assert m["median_log2_ratio"] == pytest.approx(-1.0)

    def test_at_least_halved_is_counted(self):
        """A cell that lost more than half its nuclear signal between cycles."""
        m = cycle_ratio_metrics(
            np.array([100.0, 100.0, 100.0, 100.0]),
            np.array([100.0, 90.0, 20.0, 10.0]),
        )
        assert m["n_below_half"] == 2
        assert m["fraction_below_half"] == 0.5

    def test_zero_signal_is_undefined_not_extreme(self):
        """A cell with no first-cycle signal has no baseline, so it is excluded.

        Dividing by it would invent an enormous ratio and move the median, which
        would report photobleaching that did not happen.
        """
        m = cycle_ratio_metrics(
            np.array([0.0, 100.0, 100.0]),
            np.array([50.0, 100.0, 100.0]),
        )
        assert m["n_undefined"] == 1
        assert m["n_usable"] == 2
        assert m["median_log2_ratio"] == 0.0

    def test_zero_in_the_last_cycle_is_also_undefined(self):
        m = cycle_ratio_metrics(np.array([100.0, 100.0]), np.array([0.0, 100.0]))
        assert m["n_undefined"] == 1

    def test_every_cell_undefined_says_so(self):
        m = cycle_ratio_metrics(np.array([0.0, 0.0]), np.array([1.0, 1.0]))
        assert "note" in m
        assert "histogram" not in m

    def test_tail_is_clipped_not_dropped(self):
        """Counts beyond the drawn range are reported rather than silently binned in."""
        m = cycle_ratio_metrics(np.array([1.0, 1.0]), np.array([1024.0, 1.0]), clip=4.0)
        assert m["n_above_histogram_max"] == 1
        assert sum(m["histogram"]) == 2

    def test_histogram_is_symmetric_about_zero(self):
        m = cycle_ratio_metrics(np.array([1.0]), np.array([1.0]), n_bins=8, clip=4.0)
        assert m["histogram_min"] == -4.0
        assert m["histogram_max"] == 4.0
        assert m["histogram_bin_width"] == 1.0

    def test_length_mismatch_refused(self):
        with pytest.raises(ValueError, match="differ in length"):
            cycle_ratio_metrics(np.array([1.0]), np.array([1.0, 2.0]))

    def test_no_cells_refused(self):
        with pytest.raises(ValueError, match="no cells"):
            cycle_ratio_metrics(np.array([]), np.array([]))
