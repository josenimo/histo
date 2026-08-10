"""Window selection, intensity scaling and compositing.

The parts of qc_images.py that decide *what* gets shown and *how bright*, which are
the parts that can be wrong without looking wrong. Clustering and polygon drawing are
not here: they need scanpy and PIL and are exercised against the real store.
"""

import numpy as np
import pytest
from qc_images import composite, pick_windows, stretch, window_counts


class TestWindowCounts:
    def test_counts_into_the_right_cell(self):
        centroids = np.array([[10.0, 10.0], [1500.0, 10.0], [1500.0, 1500.0]])
        counts = window_counts(centroids, (2000, 2000), 1000)
        assert counts.shape == (2, 2)
        assert counts[0, 0] == 1
        assert counts[0, 1] == 1
        assert counts[1, 1] == 1

    def test_grid_covers_a_ragged_edge(self):
        """An image not divisible by the window still gets a cell for the remainder."""
        counts = window_counts(np.array([[2100.0, 50.0]]), (300, 2200), 1000)
        assert counts.shape == (1, 3)
        assert counts[0, 2] == 1

    def test_centroid_on_the_far_edge_is_clamped(self):
        """A centroid exactly at the image width would index one cell past the end."""
        counts = window_counts(np.array([[2000.0, 2000.0]]), (2000, 2000), 1000)
        assert counts.sum() == 1

    def test_empty_windows_are_zero(self):
        counts = window_counts(np.array([[10.0, 10.0]]), (2000, 2000), 1000)
        assert counts.sum() == 1
        assert (counts == 0).sum() == 3


class TestPickWindows:
    def test_spans_the_density_range(self):
        """The whole point: dense, middling and sparse, not six crowded ones."""
        counts = np.arange(1, 101).reshape(10, 10)
        picks = pick_windows(counts, 6)
        assert len(picks) == 6
        bands = {p["density_band"] for p in picks}
        assert {"dense", "medium", "sparse"} <= bands

    def test_densest_first(self):
        counts = np.arange(1, 101).reshape(10, 10)
        picks = pick_windows(counts, 6)
        assert picks[0]["n_cells"] == 100
        assert picks[0]["density_rank"] == 1
        assert picks[-1]["n_cells"] < picks[0]["n_cells"]

    def test_empty_windows_are_never_picked(self):
        """There is nothing to inspect in an empty frame."""
        counts = np.zeros((10, 10), dtype=int)
        counts[3, 4] = 12
        counts[7, 1] = 5
        picks = pick_windows(counts, 6)
        assert len(picks) == 2
        assert all(p["n_cells"] > 0 for p in picks)

    def test_all_empty_gives_nothing(self):
        assert pick_windows(np.zeros((4, 4), dtype=int), 6) == []

    def test_fewer_windows_than_asked_for(self):
        counts = np.zeros((4, 4), dtype=int)
        counts[0, 0] = 3
        assert len(pick_windows(counts, 6)) == 1

    def test_reports_the_pool_it_chose_from(self):
        """A rank means nothing without the number of candidates."""
        counts = np.arange(1, 26).reshape(5, 5)
        picks = pick_windows(counts, 3)
        assert all(p["n_nonempty_windows"] == 25 for p in picks)

    def test_coordinates_match_the_count(self):
        counts = np.zeros((5, 5), dtype=int)
        counts[2, 3] = 99
        pick = pick_windows(counts, 1)[0]
        assert (pick["grid_x"], pick["grid_y"]) == (3, 2)
        assert pick["n_cells"] == 99


class TestStretch:
    def test_maps_bounds_onto_the_full_range(self):
        out = stretch(np.array([[100, 2365]]), 100.0, 2365.0)
        assert out[0, 0] == 0
        assert out[0, 1] == 255

    def test_clips_outside_the_bounds(self):
        """Values past the display range saturate rather than wrapping."""
        out = stretch(np.array([[0, 99999]]), 100.0, 2365.0)
        assert out[0, 0] == 0
        assert out[0, 1] == 255

    def test_degenerate_bounds_do_not_divide_by_zero(self):
        """A uniform window has lo == hi, which a naive scale would divide by."""
        out = stretch(np.array([[7, 7]]), 7.0, 7.0)
        assert out.dtype == np.uint8
        assert out[0, 0] == 0

    def test_returns_eight_bit(self):
        assert stretch(np.array([[0, 1000]]), 0.0, 2000.0).dtype == np.uint8

    def test_is_linear_between_the_bounds(self):
        out = stretch(np.array([[0, 50, 100]]), 0.0, 100.0)
        assert out[0, 1] == pytest.approx(127, abs=1)


class TestComposite:
    def test_single_grey_plane(self):
        plane = np.array([[0, 255]], dtype=np.uint8)
        rgb = composite([(plane, (1.0, 1.0, 1.0))])
        assert rgb.shape == (1, 2, 3)
        assert tuple(rgb[0, 1]) == (255, 255, 255)

    def test_two_channels_land_in_their_own_hues(self):
        """Marker into magenta, nuclear into green, which is the pair that is drawn."""
        marker = np.array([[255, 0]], dtype=np.uint8)
        nuclear = np.array([[0, 255]], dtype=np.uint8)
        rgb = composite([(marker, (1.0, 0.0, 1.0)), (nuclear, (0.0, 1.0, 0.0))])
        assert tuple(rgb[0, 0]) == (255, 0, 255)
        assert tuple(rgb[0, 1]) == (0, 255, 0)

    def test_overlap_saturates_without_wrapping(self):
        """Two bright channels sum past 255, which must clip and not overflow uint8."""
        a = np.array([[255]], dtype=np.uint8)
        rgb = composite([(a, (1.0, 0.0, 1.0)), (a, (1.0, 1.0, 0.0))])
        assert tuple(rgb[0, 0]) == (255, 255, 255)
        assert rgb.dtype == np.uint8

    def test_output_is_uint8(self):
        assert composite([(np.zeros((2, 2), dtype=np.uint8), (1.0, 1.0, 1.0))]).dtype == np.uint8
