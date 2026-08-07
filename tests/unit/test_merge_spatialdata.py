"""Core identity and table relinking in the TMA merge.

The naming rules here decide whether a merged slide's elements can be traced back
to the core they came from, which was an explicit requirement.
"""

import pytest
from merge_spatialdata import SEP, core_id_from_path, retarget_table

pd = pytest.importorskip("pandas", reason="retarget_table needs pandas")

from pathlib import Path  # noqa: E402


class TestCoreIdFromPath:
    def test_strips_zarr(self):
        assert core_id_from_path(Path("exemplar-002_core001.zarr")) == "exemplar-002_core001"

    def test_ignores_parent_directories(self):
        assert core_id_from_path(Path("/a/b/c/slide_core012.zarr")) == "slide_core012"

    def test_tolerates_missing_suffix(self):
        assert core_id_from_path(Path("slide_core001")) == "slide_core001"

    def test_keeps_internal_dots(self):
        assert core_id_from_path(Path("slide.v2_core001.zarr")) == "slide.v2_core001"


class FakeTable:
    """Enough of an AnnData for retarget_table: .uns and .obs."""

    def __init__(self, region, region_key="region", n=3):
        self.uns = {"spatialdata_attrs": {"region": region, "region_key": region_key}}
        self.obs = pd.DataFrame({region_key: [region if isinstance(region, str) else region[0]] * n})


class TestRetargetTable:
    def test_string_region_is_renamed(self):
        core = "slide_core001"
        rename = {"cellpose_boundaries": f"{core}{SEP}cellpose_boundaries"}
        t = retarget_table(FakeTable("cellpose_boundaries"), rename, core)

        assert t.uns["spatialdata_attrs"]["region"] == f"{core}{SEP}cellpose_boundaries"
        assert set(t.obs["region"]) == {f"{core}{SEP}cellpose_boundaries"}

    def test_region_stays_a_string_not_a_list(self):
        """SpatialData treats str and list differently; the shape must survive."""
        core = "c1"
        t = retarget_table(FakeTable("b"), {"b": f"{core}{SEP}b"}, core)
        assert isinstance(t.uns["spatialdata_attrs"]["region"], str)

    def test_list_region_stays_a_list(self):
        core = "c1"
        rename = {"b1": f"{core}{SEP}b1", "b2": f"{core}{SEP}b2"}
        t = retarget_table(FakeTable(["b1", "b2"]), rename, core)
        assert t.uns["spatialdata_attrs"]["region"] == [f"{core}{SEP}b1", f"{core}{SEP}b2"]

    def test_unknown_region_refused(self):
        """A table pointing at an element this core does not have is a real error.

        Silently leaving it would produce a merged object whose tables annotate
        nothing, which SpatialData would not necessarily complain about.
        """
        with pytest.raises(ValueError, match="not found"):
            retarget_table(FakeTable("some_other_element"), {"b": "c1__b"}, "c1")

    def test_missing_attrs_refused(self):
        t = FakeTable("b")
        t.uns = {}
        with pytest.raises(ValueError, match="spatialdata_attrs"):
            retarget_table(t, {"b": "c1__b"}, "c1")


class TestElementNaming:
    """The rule that keeps core identity visible without doubling it."""

    @staticmethod
    def new_name(core, name):
        return name if name == core else f"{core}{SEP}{name}"

    def test_shapes_get_the_core_prefix(self):
        assert self.new_name("c1", "cellpose_boundaries") == "c1__cellpose_boundaries"

    def test_image_named_after_the_core_is_not_doubled(self):
        """sopa names the image after the sample, which for a core IS the core ID."""
        assert self.new_name("exemplar-002_core001", "exemplar-002_core001") == ("exemplar-002_core001")

    def test_names_stay_unique_across_cores(self):
        cores = ["s_core001", "s_core002", "s_core003"]
        names = ["cellpose_boundaries", "image_patches", "table"]
        out = [self.new_name(c, n) for c in cores for n in names]
        out += [self.new_name(c, c) for c in cores]
        assert len(set(out)) == len(out)
