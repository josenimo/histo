"""Tests for the obs columns written by set_cell_metadata.py."""

import pytest
from set_cell_metadata import label_cells

pd = pytest.importorskip("pandas", reason="label_cells needs pandas")


def sopa_obs(n=3):
    """obs as sopa's aggregation leaves it: slide is the image element name."""
    return pd.DataFrame({"slide": pd.Categorical(["TMA01_core001_backsub"] * n), "area": [1.0] * n})


class TestLabelCells:
    def test_slide_replaces_sopa_value(self):
        obs = label_cells(sopa_obs(), slide="TMA01")
        assert list(obs["slide"]) == ["TMA01"] * 3

    def test_core_id_written_on_tma(self):
        obs = label_cells(sopa_obs(), slide="TMA01", core_id="TMA01_core001")
        assert list(obs["core_id"]) == ["TMA01_core001"] * 3

    def test_no_core_id_column_off_tma(self):
        """Its absence is what says the cells did not come from a TMA."""
        obs = label_cells(sopa_obs(), slide="WSI01")
        assert "core_id" not in obs

    def test_columns_are_categorical(self):
        """Matches sopa's dtype, so concatenated tables stay compact."""
        obs = label_cells(sopa_obs(), slide="TMA01", core_id="TMA01_core001")
        assert isinstance(obs["slide"].dtype, pd.CategoricalDtype)
        assert isinstance(obs["core_id"].dtype, pd.CategoricalDtype)

    def test_other_columns_untouched(self):
        obs = label_cells(sopa_obs(), slide="TMA01")
        assert list(obs["area"]) == [1.0] * 3

    def test_empty_table(self):
        """A core with no cells still gets the columns."""
        obs = label_cells(sopa_obs(n=0), slide="TMA01", core_id="TMA01_core001")
        assert {"slide", "core_id"} <= set(obs.columns)
        assert len(obs) == 0

    def test_blank_slide_refused(self):
        with pytest.raises(ValueError, match="slide"):
            label_cells(sopa_obs(), slide="")
