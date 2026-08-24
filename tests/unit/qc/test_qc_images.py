"""Window selection, intensity scaling and compositing.

The parts of qc_images.py that decide *what* gets shown and *how bright*, which are
the parts that can be wrong without looking wrong. Clustering and polygon drawing are
not here: they need scanpy and PIL and are exercised against the real store.
"""

import numpy as np
import pytest
from qc_images import (
    clustering_exclusions,
    composite,
    pick_windows,
    select_nuclear_channels,
    stretch,
    window_counts,
)


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


def _rows(*spec):
    """Marker rows as (name, role, compartment, background) tuples."""
    return [
        {
            "channel_number": i + 1,
            "cycle_number": 1,
            "marker_name": name,
            "channel_role": role,
            "channel_compartment": comp,
            "background": bg,
        }
        for i, (name, role, comp, bg) in enumerate(spec)
    ]


class TestSelectNuclearChannels:
    def test_the_exemplar001_regression(self):
        """Three nuclear stains, none named DAPI.

        This is the case that failed the run: the old code matched the literal
        "DAPI" against the channel names, found nothing, and raised "no channel
        matching 'DAPI'" while the sheet in the same task said `dna` three times.
        """
        names = ["DNA_6", "ELANE", "DNA_7", "CD11B", "DNA_8", "ECAD"]
        rows = _rows(
            ("DNA_6", "dna", "nuclear", None),
            ("ELANE", "marker", "cytoplasm", None),
            ("DNA_7", "dna", "nuclear", None),
            ("CD11B", "marker", "cytoplasm", None),
            ("DNA_8", "dna", "nuclear", None),
            ("ECAD", "marker", "cytoplasm", None),
        )
        got, how = select_nuclear_channels(names, rows)
        assert got == ["DNA_6", "DNA_7", "DNA_8"]
        assert how == "channel_role 'dna'"

    def test_ordered_by_the_store_not_the_sheet(self):
        """The table's column order is what indexes the pixels."""
        names = ["DNA_8", "DNA_6"]
        rows = _rows(("DNA_6", "dna", None, None), ("DNA_8", "dna", None, None))
        got, _ = select_nuclear_channels(names, rows)
        assert got == ["DNA_8", "DNA_6"]

    def test_channel_dropped_from_the_store_is_not_returned(self):
        """The sheet says what was acquired; the table says what survived."""
        rows = _rows(("DNA_6", "dna", None, None), ("DNA_7", "dna", None, None))
        got, _ = select_nuclear_channels(["DNA_6"], rows)
        assert got == ["DNA_6"]

    def test_no_marker_sheet_falls_back_to_dapi(self):
        got, how = select_nuclear_channels(["DAPI_1", "CD45"], None)
        assert got == ["DAPI_1"]
        assert "no marker sheet given" in how

    def test_explicit_pattern_without_a_sheet(self):
        got, how = select_nuclear_channels(["Hoechst", "CD45"], None, pattern="hoechst")
        assert got == ["Hoechst"]
        assert "hoechst" in how

    def test_empty_when_nothing_matches(self):
        """Empty rather than raising, so the caller can name the route in the error."""
        rows = _rows(("CD45", "marker", None, None))
        got, how = select_nuclear_channels(["CD45"], rows)
        assert got == []
        assert how == "channel_role 'dna'"


class TestClusteringExclusions:
    def test_nuclear_autofluorescence_and_blank_all_held_out(self):
        rows = _rows(
            ("DNA_6", "dna", "nuclear", None),
            ("AF_Cy5", "autofluorescence", None, None),
            ("Empty_FITC", "blank", None, None),
            ("CD45", "marker", "membrane", None),
        )
        got = clustering_exclusions(["DNA_6"], rows)
        assert set(got) == {"DNA_6", "AF_Cy5", "Empty_FITC"}
        assert "CD45" not in got

    def test_blank_channel_was_previously_missed(self):
        """The regression this half fixes.

        A blank channel that no other channel names as its background was clustered
        on, so an all-but-empty channel could define a cluster of its own. Only
        `channel_role` catches it.
        """
        rows = _rows(("Empty_FITC", "blank", None, None), ("CD45", "marker", None, None))
        assert "Empty_FITC" in clustering_exclusions([], rows)

    def test_autofluorescence_caught_without_a_background_reference(self):
        """Previously only excluded if some other channel pointed at it."""
        rows = _rows(("AF_Cy5", "autofluorescence", None, None), ("CD45", "marker", None, None))
        assert "AF_Cy5" in clustering_exclusions([], rows)

    def test_background_column_still_honoured(self):
        """A sheet with no roles must keep working the way it used to."""
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "AF", "background": None},
            {"channel_number": 2, "cycle_number": 1, "marker_name": "CD45", "background": "AF"},
        ]
        assert "AF" in clustering_exclusions([], rows)

    def test_reason_is_recorded_per_channel(self):
        rows = _rows(
            ("DNA_6", "dna", None, None),
            ("AF_Cy5", "autofluorescence", None, None),
            ("CD45", "marker", None, "AF_Cy5"),
        )
        got = clustering_exclusions(["DNA_6"], rows)
        assert got["DNA_6"] == "nuclear stain"
        assert got["AF_Cy5"] == "channel_role 'autofluorescence'"

    def test_first_reason_wins(self):
        """A nuclear channel also named as a background stays labelled nuclear.

        setdefault rather than assignment, so the reason a reader sees is the one
        that actually decided it.
        """
        rows = _rows(("DNA_6", "dna", None, None), ("CD45", "marker", None, "DNA_6"))
        assert clustering_exclusions(["DNA_6"], rows)["DNA_6"] == "nuclear stain"

    def test_no_sheet_excludes_only_the_nuclear_channels(self):
        assert clustering_exclusions(["DAPI"], None) == {"DAPI": "nuclear stain"}
