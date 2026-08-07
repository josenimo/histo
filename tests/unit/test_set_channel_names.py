"""Marker sheet parsing and channel-name reading.

Every case here is one that has actually happened or is one step away from it.
"""

import json

import pytest
from set_channel_names import channel_labels, read_marker_names


def write(tmp_path, text, name="markers.csv"):
    p = tmp_path / name
    p.write_text(text)
    return p


class TestReadMarkerNames:
    def test_in_order(self, tmp_path):
        p = write(tmp_path, "channel_number,marker_name\n1,DNA_1\n2,CD45\n3,CD3\n")
        assert read_marker_names(p) == ["DNA_1", "CD45", "CD3"]

    def test_sorted_not_file_order(self, tmp_path):
        """File order is not trusted; channel_number decides."""
        p = write(tmp_path, "channel_number,marker_name\n3,CD3\n1,DNA_1\n2,CD45\n")
        assert read_marker_names(p) == ["DNA_1", "CD45", "CD3"]

    def test_gaps_are_allowed(self, tmp_path):
        """backsub removes background channels, leaving channel_number with holes.

        Relative order is what matters, not contiguity.
        """
        p = write(tmp_path, "channel_number,marker_name\n1,DNA_1\n4,CD45\n7,SMA\n")
        assert read_marker_names(p) == ["DNA_1", "CD45", "SMA"]

    def test_extra_columns_ignored(self, tmp_path):
        p = write(
            tmp_path,
            "channel_number,cycle_number,marker_name,filter\n1,1,DNA_1,DAPI\n2,1,CD45,FITC\n",
        )
        assert read_marker_names(p) == ["DNA_1", "CD45"]

    def test_whitespace_stripped(self, tmp_path):
        p = write(tmp_path, "channel_number,marker_name\n1, DNA_1 \n2,CD45\n")
        assert read_marker_names(p) == ["DNA_1", "CD45"]

    def test_blank_name_refused(self, tmp_path):
        """A blank name would become a blank column in the feature matrix."""
        p = write(tmp_path, "channel_number,marker_name\n1,DNA_1\n2,\n")
        with pytest.raises(ValueError, match="blank marker_name"):
            read_marker_names(p)

    def test_duplicate_names_refused(self, tmp_path):
        """Duplicates make feature-matrix columns ambiguous."""
        p = write(tmp_path, "channel_number,marker_name\n1,DNA_1\n2,DNA_1\n")
        with pytest.raises(ValueError, match="duplicate marker names"):
            read_marker_names(p)

    def test_missing_column_refused(self, tmp_path):
        p = write(tmp_path, "channel,marker\n1,DNA_1\n")
        with pytest.raises(ValueError, match="no 'channel_number' column"):
            read_marker_names(p)

    def test_empty_refused(self, tmp_path):
        p = write(tmp_path, "channel_number,marker_name\n")
        with pytest.raises(ValueError, match="no rows"):
            read_marker_names(p)


def make_store(tmp_path, element="img", labels=("Channel:0:0", "Channel:0:1")):
    """The minimum of a SpatialData store that channel_labels() reads."""
    d = tmp_path / "s.zarr" / "images" / element
    d.mkdir(parents=True)
    (d / "zarr.json").write_text(
        json.dumps(
            {"attributes": {"ome": {"omero": {"channels": [{"label": x} for x in labels]}}}}
        )
    )
    return tmp_path / "s.zarr"


class TestChannelLabels:
    def test_reads_labels(self, tmp_path):
        store = make_store(tmp_path, labels=("DNA_1", "CD45"))
        assert channel_labels(store, "img") == ["DNA_1", "CD45"]

    def test_missing_element_refused(self, tmp_path):
        store = make_store(tmp_path)
        with pytest.raises(FileNotFoundError, match="does not exist"):
            channel_labels(store, "nope")

    def test_unexpected_layout_refused(self, tmp_path):
        """If spatialdata moves channel names, fail loudly rather than return nothing.

        The earlier version of this function fell back silently on any exception,
        which would have hidden exactly this.
        """
        store = make_store(tmp_path)
        (store / "images" / "img" / "zarr.json").write_text(json.dumps({"attributes": {}}))
        with pytest.raises(ValueError, match="layout has changed"):
            channel_labels(store, "img")
