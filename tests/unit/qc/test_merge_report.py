"""The slide summary, and what it refuses to claim.

Most of these are about roll-up semantics rather than arithmetic: a slide check
passes only when every core passes, and the interesting cases are the ones where
some cores are fine. The numbers that are arithmetic come from the real
exemplar-002 run, so a regression disagrees with something that happened.
"""

import json

import pytest
from merge_report import (
    build,
    channel_sets,
    core_label,
    read_cores,
    slide_totals,
)

# The four cores of the real 2-cycle TMA run: cells, degenerate cells, patches.
EXEMPLAR002 = [
    ("exemplar-002_core001", 7472, 7, 4),
    ("exemplar-002_core002", 4779, 11, 4),
    ("exemplar-002_core003", 7604, 15, 4),
    ("exemplar-002_core004", 9678, 14, 4),
]

CHANNELS = ["DNA_1", "AF488", "AF555", "AF647", "DNA_2"]
ROLES = {"DNA_1": "dna", "AF488": "marker", "AF555": "marker", "AF647": "marker", "DNA_2": "dna"}


def core(name, n_cells=1000, degenerate=0, patches=4, empty=0, channels=None, **over):
    channels = channels or CHANNELS
    d = {
        "sample": name,
        "store": f"/runs/{name}.zarr",
        "image_element": name,
        "image": {"shape_cyx": [len(channels), 2896, 2896], "dtype": "uint16", "n_pyramid_levels": 1},
        "cells": {
            "n_cells": n_cells,
            "n_below_min_cell_area": degenerate,
            "fraction_below_min_cell_area": degenerate / n_cells if n_cells else 0.0,
            "min_cell_area": 10.0,
            "min": 3.9,
            "max": 2000.0,
            "mean": 500.0,
            "p50": 480.0,
        },
        "channels": {
            "n_channels": len(channels),
            "table_names": list(channels),
            "image_names": list(channels),
            "table_matches_image": True,
            "matches_marker_sheet": True,
            "roles": {"dna": [c for c in channels if ROLES.get(c) == "dna"]},
            "per_channel": {
                c: {"mean": 1000.0, "fraction_zero": 0.01, "role": ROLES.get(c, "marker")} for c in channels
            },
        },
        "patches": {"n_patches": patches, "n_empty_patches": empty},
    }
    for k, v in over.items():
        d[k] = v
    return d


def exemplar_cores():
    return [core(n, cells, deg, pat) for n, cells, deg, pat in EXEMPLAR002]


class TestSlideTotals:
    def test_sums_the_real_run(self):
        """29,533 cells is what the merged store holds, checked against it."""
        t = slide_totals(exemplar_cores())
        assert t["n_cells"] == 29533
        assert t["n_cores"] == 4
        assert t["n_below_min_cell_area"] == 47
        assert t["n_patches"] == 16

    def test_median_is_a_core_count_not_an_average(self):
        """A slide with one huge core should not report an inflated typical core."""
        t = slide_totals([core("a", 100), core("b", 100), core("c", 10000)])
        assert t["median_cells_per_core"] == 100

    def test_untiled_cores_contribute_no_patches(self):
        t = slide_totals([core("a", 100, patches=0) | {"patches": None}, core("b", 100)])
        assert t["n_patches"] == 4


class TestReadCores:
    def test_sorted_by_name_not_by_arrival(self, tmp_path):
        """Nextflow does not guarantee channel order, and a table whose rows move
        between runs cannot be diffed."""
        paths = []
        for name in ["exemplar-002_core003", "exemplar-002_core001", "exemplar-002_core002"]:
            p = tmp_path / f"{name}.json"
            p.write_text(json.dumps(core(name)))
            paths.append(p)
        assert [core_label(c) for c in read_cores(paths)] == [
            "exemplar-002_core001",
            "exemplar-002_core002",
            "exemplar-002_core003",
        ]

    def test_stub_metrics_are_skipped(self, tmp_path):
        """A -stub run writes {"sample": ..., "stub": true} and no numbers."""
        real = tmp_path / "real.json"
        real.write_text(json.dumps(core("exemplar-002_core001")))
        stub = tmp_path / "stub.json"
        stub.write_text(json.dumps({"sample": "exemplar-002_core002", "stub": True}))
        assert len(read_cores([real, stub])) == 1

    def test_all_stub_refuses_rather_than_rendering_an_empty_slide(self, tmp_path):
        p = tmp_path / "stub.json"
        p.write_text(json.dumps({"sample": "x", "stub": True}))
        with pytest.raises(ValueError, match="no numbers to summarise"):
            read_cores([p])


class TestChannelSets:
    def test_identical_cores_collapse_to_one_set(self):
        assert len(channel_sets(exemplar_cores())) == 1

    def test_a_core_with_different_channels_is_its_own_set(self):
        cores = exemplar_cores()
        cores[2]["channels"]["table_names"] = ["DNA_1", "AF488"]
        sets = channel_sets(cores)
        assert len(sets) == 2
        assert ["exemplar-002_core003"] in sets.values()

    def test_order_matters(self):
        """Same channels in a different order still means the tables cannot be
        compared column for column."""
        cores = [core("a"), core("b", channels=list(reversed(CHANNELS)))]
        assert len(channel_sets(cores)) == 2


class TestRollup:
    """A slide check passes only when every core passes."""

    def test_all_passing_says_so(self):
        page = build("exemplar-002", exemplar_cores())
        assert "Every core&#x27;s table and image agree on channel names" in page
        assert "all 4 cores" in page

    def test_one_failing_core_fails_the_slide_and_is_named(self):
        cores = exemplar_cores()
        cores[1]["channels"]["table_matches_image"] = False
        page = build("exemplar-002", cores)
        assert "1 of 4: exemplar-002_core002" in page

    def test_mismatched_channels_are_reported_as_a_slide_fact(self):
        cores = exemplar_cores()
        cores[0]["channels"]["table_names"] = ["DNA_1"]
        page = build("exemplar-002", cores)
        assert "2 different channel lists" in page

    def test_checks_absent_from_the_metrics_are_not_asserted(self):
        """A core whose metrics predate channel_role is not failing the role check,
        it is not taking it."""
        cores = [core(n) for n, *_ in EXEMPLAR002]
        for c in cores:
            del c["channels"]["roles"]
        page = build("exemplar-002", cores)
        assert "Every core declares a nuclear stain" not in page


class TestBuild:
    def test_renders_a_whole_page(self):
        page = build("exemplar-002", exemplar_cores())
        assert page.startswith("<!DOCTYPE html>")
        assert page.rstrip().endswith("</html>")

    def test_reports_the_slide_total(self):
        assert "29,533" in build("exemplar-002", exemplar_cores())

    def test_no_external_references(self):
        """Self-contained, the same rule the core report follows."""
        page = build("exemplar-002", exemplar_cores())
        assert "http://" not in page
        assert "https://" not in page

    def test_entities_are_not_double_escaped(self):
        assert "&amp;" not in build("exemplar-002", exemplar_cores())

    def test_core_specific_detail_is_left_out(self):
        """The whole point of a slide view: crops, clusters and patch layouts stay
        in the per-core reports rather than being repeated four times."""
        page = build("exemplar-002", exemplar_cores())
        for absent in ["Segmentation crops", "Cluster", "clustree", "Patch (x, y)"]:
            assert absent not in page

    def test_channel_spread_is_computed_across_cores(self):
        cores = exemplar_cores()
        for i, c in enumerate(cores):
            c["channels"]["per_channel"]["AF488"]["mean"] = 100.0 * (i + 1)
        page = build("exemplar-002", cores)
        assert "4.0×" in page  # 400 over 100

    def test_a_zero_mean_does_not_divide_by_zero(self):
        cores = exemplar_cores()
        cores[0]["channels"]["per_channel"]["AF488"]["mean"] = 0.0
        page = build("exemplar-002", cores)
        assert "inf" not in page.lower()

    def test_backsub_section_only_when_a_before_image_existed(self):
        page = build("exemplar-002", exemplar_cores())
        assert "Background subtraction, before and after" not in page

    def test_backsub_section_appears_when_it_did(self):
        """Possible only because COREOGRAPH now runs before BACKSUB, so each core
        keeps an unsubtracted twin of its own shape."""
        cores = exemplar_cores()
        for c in cores:
            c["before"] = {"image": "x.tif", "n_channels": len(CHANNELS)}
            for name in CHANNELS:
                c["channels"]["per_channel"][name]["before"] = {"fraction_zero": 0.001}
        page = build("exemplar-002", cores)
        assert "Background subtraction, before and after" in page

    def test_cycle_section_only_when_the_check_ran(self):
        page = build("exemplar-002", exemplar_cores())
        assert "Nuclear stain across cycles" not in page

    def test_cycle_section_reports_each_core(self):
        cores = exemplar_cores()
        for i, c in enumerate(cores):
            c["cycle_ratio"] = {
                "available": True,
                "median_log2_ratio": 0.01 * i,
                "fraction_below_half": 0.001,
                "n_usable": c["cells"]["n_cells"],
                "first_channel": "DNA_1",
                "last_channel": "DNA_2",
                "nuclear_selected_by": "channel_role 'dna'",
            }
        page = build("exemplar-002", cores)
        assert "Nuclear stain across cycles" in page
        assert "channel_role" in page

    def test_single_core_slide_still_renders(self):
        """A one-core array is degenerate but not an error."""
        page = build("exemplar-002", [core("exemplar-002_core001", 500)])
        assert "500" in page
