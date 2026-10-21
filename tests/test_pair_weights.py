"""Bulk connectivity files -> (source, target, weight) between VFB neurons."""
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather

from vfb_connectomics_import.connectivity.cli._common import load_pair_weights_file


def _write(path, df, chunksize):
    # several record batches, so per-batch partial sums have to be merged
    feather.write_feather(pa.Table.from_pandas(df, preserve_index=False), str(path),
                          chunksize=chunksize)


def test_sums_per_pair_across_neuropils_and_batches(tmp_path):
    # FlyWire-style: one row per pair and neuropil
    df = pd.DataFrame({"pre_pt_root_id": [1, 1, 1, 2, 3, 1],
                       "post_pt_root_id": [2, 2, 2, 1, 1, 9],
                       "neuropil": ["ME_L", "LO_L", "ME_L", "EB", "EB", "EB"],
                       "syn_count": [1, 1, 3, 2, 50, 50]})
    _write(tmp_path / "c.feather", df, chunksize=2)
    out = load_pair_weights_file(str(tmp_path / "c.feather"), [1, 2], "pre_pt_root_id",
                                 "post_pt_root_id", "syn_count", threshold=1)
    got = {(r.source, r.target): r.weight for r in out.itertuples()}
    # 1->2 summed over neuropils and batches; 2->1 kept (2 > 1); 3->1 and 1->9 are
    # not between VFB neurons
    assert got == {(1, 2): 5, (2, 1): 2}


def test_threshold_and_uint64_ids(tmp_path):
    # neuprint flat-connectome style, with uint64 body ids as the optic-lobe file has
    df = pd.DataFrame({"body_pre": pd.array([10, 10, 11], dtype="uint64"),
                       "body_post": pd.array([11, 12, 10], dtype="uint64"),
                       "weight": [2, 7, 1]})
    _write(tmp_path / "w.feather", df, chunksize=10)
    out = load_pair_weights_file(str(tmp_path / "w.feather"), [10, 11, 12], "body_pre",
                                 "body_post", "weight", threshold=1)
    assert sorted(map(tuple, out[["source", "target", "weight"]].values.tolist())) == \
        [(10, 11, 2), (10, 12, 7)]
