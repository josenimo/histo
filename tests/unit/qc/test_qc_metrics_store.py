"""The half of qc_metrics.py that reads a SpatialData store.

Split from test_qc_metrics.py because these need zarr and pyarrow while the metric
arithmetic needs only numpy. Keeping them apart means a failure here points at the
store layout and a failure there points at the maths.

Every store is built in tmp_path rather than mocked. The encodings under test are
exactly the ones real pipeline output uses -- AnnData writes a dataframe column
three different ways depending on dtype -- and a mock would assert what this file
already believes rather than what spatialdata writes.
"""

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import zarr
from qc_metrics import (
    channel_histograms,
    collect,
    image_channel_labels,
    read_column,
    sole_image_element,
)


def make_image(store, element, data):
    """One image element with an s0 array and the omero channel labels beside it.

    Mirrors the layout verified against real output: the array lives at
    `images/<element>/s0`, and channel names live in the group metadata under
    `attributes.ome.omero.channels[].label`.
    """
    images = store / "images" / element
    images.mkdir(parents=True)
    arr = zarr.create_array(store=str(images / "s0"), shape=data.shape, dtype=data.dtype, chunks=(1, 4, 4))
    arr[:] = data
    labels = [f"ch{i}" for i in range(data.shape[0])]
    (images / "zarr.json").write_text(
        json.dumps(
            {
                "zarr_format": 3,
                "node_type": "group",
                "attributes": {"ome": {"omero": {"channels": [{"label": name} for name in labels]}}},
            }
        )
    )
    return labels


def make_table(store, areas, centroids, channel_names):
    """A minimal AnnData table using all three column encodings at once."""
    root = zarr.open_group(str(store / "tables" / "table"), mode="w")
    root.create_array("obs/area", shape=(len(areas),), dtype="f8")[:] = areas
    root.create_array("obsm/spatial", shape=centroids.shape, dtype="f8")[:] = centroids

    # var/_index as nullable strings, which is how the real store holds it.
    var_index = root.create_group("var/_index")
    var_index.attrs["encoding-type"] = "nullable-string-array"
    values = var_index.create_array("values", shape=(len(channel_names),), dtype="<U16")
    values[:] = np.array(channel_names, dtype="<U16")
    mask = var_index.create_array("mask", shape=(len(channel_names),), dtype="bool")
    mask[:] = False

    # obs/region as categorical, the other real encoding.
    region = root.create_group("obs/region")
    region.attrs["encoding-type"] = "categorical"
    cats = region.create_array("categories", shape=(1,), dtype="<U32")
    cats[:] = np.array(["cellpose_boundaries"], dtype="<U32")
    codes = region.create_array("codes", shape=(len(areas),), dtype="i1")
    codes[:] = 0


def make_patches(store, bboxes):
    """The image_patches shapes element, as a geopandas-written parquet would be."""
    d = store / "shapes" / "image_patches"
    d.mkdir(parents=True)
    table = pa.table({"bboxes": pa.array([list(b) for b in bboxes], type=pa.list_(pa.int64()))})
    pq.write_table(table, d / "shapes.parquet")


@pytest.fixture
def store(tmp_path):
    """A two-channel 1x8x8 store with four cells and two patches."""
    s = tmp_path / "sample.zarr"
    s.mkdir()
    data = np.zeros((2, 8, 8), dtype=np.uint16)
    data[0, 0, 0] = 100
    data[0, 1, 1] = 300
    data[1, :, :] = 7
    names = make_image(s, "sample", data)
    areas = np.array([4.0, 50.0, 900.0, 1000.0])
    centroids = np.array([[1.0, 1.0], [2.0, 2.0], [6.0, 6.0], [7.0, 7.0]])
    make_table(s, areas, centroids, names)
    make_patches(s, [[0, 0, 4, 4], [4, 4, 8, 8]])
    return s


class TestReadColumn:
    def test_plain_array(self, store):
        col = read_column(zarr.open_group(str(store / "tables/table"), mode="r")["obs"]["area"])
        assert list(col) == [4.0, 50.0, 900.0, 1000.0]

    def test_categorical_is_expanded(self, store):
        """obs/region and obs/slide arrive as categories plus codes, not strings."""
        col = read_column(zarr.open_group(str(store / "tables/table"), mode="r")["obs"]["region"])
        assert list(col) == ["cellpose_boundaries"] * 4

    def test_nullable_string(self, store):
        col = read_column(zarr.open_group(str(store / "tables/table"), mode="r")["var"]["_index"])
        assert list(col) == ["ch0", "ch1"]

    def test_unknown_encoding_refused(self, tmp_path):
        """Guessing from the group's keys would break on the first added key."""
        g = zarr.open_group(str(tmp_path / "x.zarr"), mode="w")
        node = g.create_group("weird")
        node.attrs["encoding-type"] = "something-new"
        with pytest.raises(ValueError, match="unsupported AnnData column encoding"):
            read_column(node)


class TestSoleImageElement:
    def test_finds_the_only_one(self, store):
        assert sole_image_element(store) == "sample"

    def test_two_elements_refused(self, store):
        """The guard the pipeline actually depends on: exactly one image."""
        extra = store / "images" / "other"
        extra.mkdir()
        (extra / "zarr.json").write_text("{}")
        with pytest.raises(ValueError, match="expected exactly one image element, found 2"):
            sole_image_element(store)

    def test_not_a_store_refused(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not a SpatialData store"):
            sole_image_element(tmp_path / "nope.zarr")


class TestImageChannelLabels:
    def test_reads_omero_labels(self, store):
        assert image_channel_labels(store, "sample") == ["ch0", "ch1"]

    def test_missing_element_refused(self, store):
        with pytest.raises(FileNotFoundError, match="not an image element"):
            image_channel_labels(store, "absent")

    def test_missing_omero_block_refused(self, store):
        (store / "images" / "sample" / "zarr.json").write_text('{"attributes": {}}')
        with pytest.raises(ValueError, match="no attributes.ome.omero.channels"):
            image_channel_labels(store, "sample")


class TestChannelHistograms:
    def test_counts_every_pixel_exactly(self, store):
        arr = zarr.open_array(str(store / "images/sample/s0"), mode="r")
        hists, dtype_max = channel_histograms(arr)
        assert dtype_max == 65535
        assert len(hists) == 2
        # Channel 0: 62 zeros, one 100, one 300, over 64 pixels.
        assert hists[0][0] == 62
        assert hists[0][100] == 1
        assert hists[0][300] == 1
        assert hists[0].sum() == 64
        assert hists[1][7] == 64

    def test_band_size_does_not_change_the_result(self, store):
        """Streaming is an implementation detail; the histogram must not depend on it.

        This is the property that makes the row-band loop safe to tune for memory.
        """
        arr = zarr.open_array(str(store / "images/sample/s0"), mode="r")
        one_band, _ = channel_histograms(arr, band_rows=8)
        many_bands, _ = channel_histograms(arr, band_rows=1)
        assert np.array_equal(one_band[0], many_bands[0])
        assert np.array_equal(one_band[1], many_bands[1])

    def test_non_3d_refused(self, tmp_path):
        arr = zarr.create_array(store=str(tmp_path / "flat.zarr"), shape=(4, 4), dtype="u2")
        with pytest.raises(ValueError, match=r"expected a \(c, y, x\) image"):
            channel_histograms(arr)

    def test_signed_dtype_refused(self, tmp_path):
        """Exact histograms index by value, so a negative value has no bin."""
        arr = zarr.create_array(store=str(tmp_path / "signed.zarr"), shape=(1, 4, 4), dtype="i2")
        with pytest.raises(ValueError, match="is signed"):
            channel_histograms(arr)


class TestCollect:
    def test_end_to_end(self, store):
        m = collect(store, min_cell_area=10.0, markers=None)
        assert m["image_element"] == "sample"
        assert m["image"]["shape_cyx"] == [2, 8, 8]
        assert m["image"]["dtype"] == "uint16"
        assert m["cells"]["n_cells"] == 4
        assert m["cells"]["n_below_min_cell_area"] == 1
        assert m["channels"]["n_channels"] == 2
        assert m["channels"]["table_matches_image"] is True
        assert sorted(m["channels"]["per_channel"]) == ["ch0", "ch1"]
        assert m["patches"]["n_patches"] == 2
        assert m["patches"]["n_empty_patches"] == 0

    def test_output_is_json_serialisable(self, store):
        """The whole point is a machine-readable file, so numpy scalars must not leak.

        json.dumps on a np.int64 raises, and it would only be discovered on a real
        run rather than here.
        """
        json.dumps(collect(store, min_cell_area=10.0, markers=None))

    def test_marker_mismatch_is_reported_not_raised(self, store):
        """QC observes; it does not decide. A mismatch is a field, not an exception."""
        m = collect(store, min_cell_area=10.0, markers=["wrong", "names"])
        assert m["channels"]["matches_marker_sheet"] is False
        assert m["channels"]["marker_sheet_names"] == ["wrong", "names"]

    def test_marker_match_reported(self, store):
        m = collect(store, min_cell_area=10.0, markers=["ch0", "ch1"])
        assert m["channels"]["matches_marker_sheet"] is True

    def test_untiled_run_has_no_patches(self, store):
        """Absent, not zero: a reader must tell "not tiled" from "tiled and empty"."""
        (store / "shapes" / "image_patches" / "shapes.parquet").unlink()
        assert collect(store, min_cell_area=10.0, markers=None)["patches"] is None

    def test_table_image_disagreement_is_caught(self, store):
        """If the table and image disagree, every per-cell intensity is ambiguous."""
        meta = store / "images" / "sample" / "zarr.json"
        meta.write_text(
            json.dumps(
                {"attributes": {"ome": {"omero": {"channels": [{"label": "other"}, {"label": "names"}]}}}}
            )
        )
        m = collect(store, min_cell_area=10.0, markers=None)
        assert m["channels"]["table_matches_image"] is False
