"""QC metric arithmetic, and the trace parser.

Only the pure functions are here. They need numpy and nothing else, which keeps
this file runnable in the CI job that installs pytest and pandas. Reading a real
store needs zarr and pyarrow, so `read_column`, `collect` and `channel_histograms`
are exercised against real pipeline output rather than mocked here.

The numbers in the expectations come from the published WSI run in scratch/output
wherever a real value was available, so a regression shows up as a disagreement
with something that actually happened.
"""

import numpy as np
import pytest
from qc_metrics import (
    _parse_size,
    _pct_key,
    area_metrics,
    cells_per_patch,
    channel_metrics,
    effective_bit_depth,
    parse_trace,
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


class TestParseSize:
    def test_gigabytes(self):
        assert _parse_size("5.1 GB") == int(5.1 * 1024**3)

    def test_megabytes(self):
        assert _parse_size("889 MB") == 889 * 1024**2

    def test_missing_reading_is_none(self):
        """macOS without a container engine reports no metrics at all.

        One real trace on this pipeline is entirely dashes, so this must not raise.
        """
        assert _parse_size("-") is None
        assert _parse_size("") is None
        assert _parse_size(None) is None

    def test_unparseable_is_none(self):
        assert _parse_size("lots") is None
        assert _parse_size("5 PARSECS") is None

    def test_bare_number_is_bytes(self):
        assert _parse_size("1024") == 1024


TRACE_HEADER = "task_id\thash\tname\tstatus\texit\tattempt\tpeak_rss\n"


def write_trace(tmp_path, *rows):
    p = tmp_path / "execution_trace_test.txt"
    p.write_text(TRACE_HEADER + "".join(rows))
    return p


class TestParseTrace:
    def test_all_completed(self, tmp_path):
        p = write_trace(
            tmp_path,
            "1\tab/cd\tFOO (s)\tCOMPLETED\t0\t1\t5.1 GB\n",
            "2\tef/gh\tBAR (s)\tCOMPLETED\t0\t1\t1.9 GB\n",
        )
        m = parse_trace(p)
        assert m["n_tasks"] == 2
        assert m["n_failed"] == 0
        assert m["by_status"] == {"COMPLETED": 2}
        assert m["peak_rss_task"] == "FOO (s)"

    def test_failure_named(self, tmp_path):
        """A named failing task is the difference between useful and not."""
        p = write_trace(
            tmp_path,
            "1\tab/cd\tFOO (s)\tCOMPLETED\t0\t1\t1 GB\n",
            "2\tef/gh\tBAR (s)\tFAILED\t137\t1\t-\n",
        )
        m = parse_trace(p)
        assert m["n_failed"] == 1
        assert m["failed_tasks"] == ["BAR (s)"]

    def test_cached_is_not_a_failure(self, tmp_path):
        """-resume produces CACHED rows, which are successes."""
        p = write_trace(tmp_path, "1\tab/cd\tFOO (s)\tCACHED\t0\t1\t-\n")
        m = parse_trace(p)
        assert m["n_failed"] == 0

    def test_retry_counted(self, tmp_path):
        """attempt > 1 means errorStrategy retried, which is worth surfacing."""
        p = write_trace(tmp_path, "1\tab/cd\tFOO (s)\tCOMPLETED\t0\t2\t1 GB\n")
        m = parse_trace(p)
        assert m["n_retried"] == 1
        assert m["retried_tasks"] == ["FOO (s)"]

    def test_all_metrics_missing(self, tmp_path):
        """The macOS case: rows exist, memory readings do not."""
        p = write_trace(tmp_path, "1\tab/cd\tFOO (s)\tCOMPLETED\t0\t1\t-\n")
        m = parse_trace(p)
        assert m["peak_rss_bytes"] is None
        assert m["top_memory_tasks"] == []

    def test_top_memory_is_sorted_and_capped(self, tmp_path):
        rows = [f"{i}\tab/cd\tT{i}\tCOMPLETED\t0\t1\t{i} GB\n" for i in range(1, 8)]
        m = parse_trace(write_trace(tmp_path, *rows))
        assert [t["name"] for t in m["top_memory_tasks"]] == ["T7", "T6", "T5", "T4", "T3"]

    def test_no_rows_refused(self, tmp_path):
        p = tmp_path / "execution_trace_empty.txt"
        p.write_text(TRACE_HEADER)
        with pytest.raises(ValueError, match="no task rows"):
            parse_trace(p)
