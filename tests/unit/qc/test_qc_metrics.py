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
    cells_per_patch,
    channel_metrics,
    channels_with_role,
    compartments_by_channel,
    cycle_ratio_metrics,
    effective_bit_depth,
    nuclear_cycle_pair,
    patch_metrics,
    percentiles_from_histogram,
    read_marker_cycles,
    resolve_nuclear_rows,
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
        """Rows with neither a role nor a DAPI-like name: nothing to compare.

        Returns None rather than picking an arbitrary channel. These rows carry no
        `channel_role` at all, which is the pre-channel_role sheet shape, so the
        DAPI name fallback runs and finds nothing.
        """
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


# The sheet from the exemplar001 run that exposed all of this: three nuclear stains,
# none of them named DAPI. Reused across the classes below so that a regression fails
# against the sheet that actually broke rather than against a constructed one.
EXEMPLAR001 = [
    (1, 1, "DNA_6", "dna", "nuclear"),
    (2, 1, "ELANE", "marker", "cytoplasm"),
    (3, 1, "CD57", "marker", "cytoplasm"),
    (4, 1, "CD45", "marker", "cytoplasm"),
    (5, 2, "DNA_7", "dna", "nuclear"),
    (6, 2, "CD11B", "marker", "cytoplasm"),
    (7, 2, "SMA", "marker", "cytoplasm"),
    (8, 2, "CD16", "marker", "cytoplasm"),
    (9, 3, "DNA_8", "dna", "nuclear"),
    (10, 3, "ECAD", "marker", "cytoplasm"),
    (11, 3, "FOXP3", "marker", "nuclear"),
    (12, 3, "NCAM", "marker", "cytoplasm"),
]


def exemplar_rows():
    return [
        {
            "channel_number": n,
            "cycle_number": c,
            "marker_name": m,
            "channel_role": role,
            "channel_compartment": comp,
            "background": None,
        }
        for n, c, m, role, comp in EXEMPLAR001
    ]


class TestReadMarkerCyclesRoles:
    def test_reads_role_compartment_and_background(self, tmp_path):
        p = tmp_path / "m.csv"
        p.write_text(
            "channel_number,cycle_number,marker_name,channel_role,channel_compartment,background\n"
            "1,1,DNA_6,dna,nuclear,\n"
            "2,1,CD45,marker,membrane,AF_1\n"
        )
        rows = read_marker_cycles(p)
        assert [r["channel_role"] for r in rows] == ["dna", "marker"]
        assert [r["channel_compartment"] for r in rows] == ["nuclear", "membrane"]
        assert rows[1]["background"] == "AF_1"

    def test_absent_columns_are_none_not_empty_string(self, tmp_path):
        """A sheet predating channel_role must still parse.

        None rather than "" so that "the sheet does not say" is distinguishable from
        a blank cell, which is what lets the callers decide to fall back.
        """
        p = tmp_path / "m.csv"
        p.write_text("channel_number,cycle_number,marker_name\n1,1,DAPI\n")
        row = read_marker_cycles(p)[0]
        assert row["channel_role"] is None
        assert row["channel_compartment"] is None
        assert row["background"] is None

    def test_role_is_lowercased(self, tmp_path):
        """The schema's enum is lowercase; a sheet shouting DNA still matches."""
        p = tmp_path / "m.csv"
        p.write_text("channel_number,cycle_number,marker_name,channel_role\n1,1,DNA_6,DNA\n")
        assert read_marker_cycles(p)[0]["channel_role"] == "dna"

    def test_background_keeps_its_case(self, tmp_path):
        """It names another channel, and channel names are matched exactly."""
        p = tmp_path / "m.csv"
        p.write_text(
            "channel_number,cycle_number,marker_name,channel_role,background\n1,1,CD45,marker,AF_Cy5\n"
        )
        assert read_marker_cycles(p)[0]["background"] == "AF_Cy5"

    def test_blank_cells_become_none(self, tmp_path):
        p = tmp_path / "m.csv"
        p.write_text(
            "channel_number,cycle_number,marker_name,channel_role,channel_compartment\n1,1,DNA_6,dna,  \n"
        )
        assert read_marker_cycles(p)[0]["channel_compartment"] is None


class TestResolveNuclearRows:
    def test_channel_role_finds_stains_not_called_dapi(self):
        """The regression. Three nuclear channels, zero DAPI substring matches."""
        rows, how = resolve_nuclear_rows(exemplar_rows())
        assert [r["marker_name"] for r in rows] == ["DNA_6", "DNA_7", "DNA_8"]
        assert how == "channel_role 'dna'"

    def test_role_beats_a_misleading_name(self):
        """A channel named DAPI that the sheet says is not the stain is not chosen."""
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "DAPI_leak", "channel_role": "blank"},
            {"channel_number": 2, "cycle_number": 1, "marker_name": "DNA_6", "channel_role": "dna"},
        ]
        got, how = resolve_nuclear_rows(rows)
        assert [r["marker_name"] for r in got] == ["DNA_6"]
        assert how == "channel_role 'dna'"

    def test_explicit_pattern_overrides_the_sheet(self):
        """The escape hatch for a sheet whose roles are wrong."""
        rows, how = resolve_nuclear_rows(exemplar_rows(), pattern="ELANE")
        assert [r["marker_name"] for r in rows] == ["ELANE"]
        assert "ELANE" in how

    def test_falls_back_to_dapi_without_a_role_column(self):
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "DAPI_bg"},
            {"channel_number": 2, "cycle_number": 2, "marker_name": "CD3e"},
        ]
        got, how = resolve_nuclear_rows(rows)
        assert [r["marker_name"] for r in got] == ["DAPI_bg"]
        assert "no channel_role in the sheet" in how

    def test_fallback_says_it_is_a_fallback(self):
        """The route is reported so a report can weigh the result by how it was got."""
        _, with_role = resolve_nuclear_rows(exemplar_rows())
        _, without = resolve_nuclear_rows([{"channel_number": 1, "cycle_number": 1, "marker_name": "DAPI"}])
        assert with_role != without

    def test_no_nuclear_anywhere_is_empty_not_an_error(self):
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "CD3e", "channel_role": "marker"},
        ]
        got, _ = resolve_nuclear_rows(rows)
        assert got == []


class TestNuclearCyclePairByRole:
    def test_first_and_last_cycle_by_role(self):
        """The exemplar001 sheet: cycle 1 to cycle 3, skipping DNA_7 in between."""
        assert nuclear_cycle_pair(exemplar_rows()) == ("DNA_6", "DNA_8")

    def test_single_nuclear_cycle_still_returns_none(self):
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "DNA_6", "channel_role": "dna"},
            {"channel_number": 2, "cycle_number": 2, "marker_name": "CD45", "channel_role": "marker"},
        ]
        assert nuclear_cycle_pair(rows) is None


class TestChannelsWithRole:
    def test_selects_one_role(self):
        assert channels_with_role(exemplar_rows(), "dna") == ["DNA_6", "DNA_7", "DNA_8"]

    def test_selects_several_roles_at_once(self):
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "AF", "channel_role": "autofluorescence"},
            {"channel_number": 2, "cycle_number": 1, "marker_name": "Empty", "channel_role": "blank"},
            {"channel_number": 3, "cycle_number": 1, "marker_name": "CD45", "channel_role": "marker"},
        ]
        assert channels_with_role(rows, "autofluorescence", "blank") == ["AF", "Empty"]

    def test_channel_order_is_preserved(self):
        rows = list(reversed(exemplar_rows()))
        assert channels_with_role(rows, "dna") == ["DNA_8", "DNA_7", "DNA_6"]

    def test_roleless_sheet_gives_nothing(self):
        """Empty, which is what tells a caller to fall back rather than to conclude
        that the slide has no nuclear stain."""
        rows = [{"channel_number": 1, "cycle_number": 1, "marker_name": "DAPI"}]
        assert channels_with_role(rows, "dna") == []


class TestCompartmentsByChannel:
    def test_maps_only_declared_channels(self):
        got = compartments_by_channel(exemplar_rows())
        assert got["DNA_6"] == "nuclear"
        assert got["FOXP3"] == "nuclear"
        assert got["CD45"] == "cytoplasm"
        assert len(got) == len(EXEMPLAR001)

    def test_channels_without_a_compartment_are_absent(self):
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "A", "channel_compartment": None},
            {"channel_number": 2, "cycle_number": 1, "marker_name": "B", "channel_compartment": "membrane"},
        ]
        assert compartments_by_channel(rows) == {"B": "membrane"}

    def test_multi_compartment_value_is_kept_whole(self):
        """`nuclear+cytoplasm` is one claim, not two, and the schema allows it."""
        rows = [
            {
                "channel_number": 1,
                "cycle_number": 1,
                "marker_name": "FOXP3",
                "channel_compartment": "nuclear+cytoplasm",
            }
        ]
        assert compartments_by_channel(rows) == {"FOXP3": "nuclear+cytoplasm"}


class TestRoleDeclaringSheetIsAuthoritative:
    """A sheet that declares roles is believed, including when it declares no dna.

    The alternative -- falling back to a name match when no row says `dna` -- would
    reintroduce the guess on the one input that explicitly ruled it out, and could
    pick a channel the sheet declined to call nuclear.
    """

    def test_roles_present_but_no_dna_does_not_fall_back(self):
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "DAPI_leak", "channel_role": "blank"},
            {"channel_number": 2, "cycle_number": 1, "marker_name": "CD45", "channel_role": "marker"},
        ]
        got, how = resolve_nuclear_rows(rows)
        assert got == []
        assert how == "channel_role 'dna'"

    def test_the_same_rows_without_roles_do_fall_back(self):
        """Same names, no role column: the historical behaviour is still available."""
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "DAPI_leak"},
            {"channel_number": 2, "cycle_number": 1, "marker_name": "CD45"},
        ]
        got, how = resolve_nuclear_rows(rows)
        assert [r["marker_name"] for r in got] == ["DAPI_leak"]
        assert "no channel_role in the sheet" in how

    def test_a_partly_roled_sheet_counts_as_roled(self):
        """One declared role is enough to treat the sheet as speaking for itself.

        A half-filled column is a sheet problem, and QC reports it as a missing role
        rather than papering over it with a name match.
        """
        rows = [
            {"channel_number": 1, "cycle_number": 1, "marker_name": "DAPI_leak", "channel_role": None},
            {"channel_number": 2, "cycle_number": 1, "marker_name": "CD45", "channel_role": "marker"},
        ]
        _, how = resolve_nuclear_rows(rows)
        assert how == "channel_role 'dna'"
