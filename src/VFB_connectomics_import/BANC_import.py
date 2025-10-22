"""
BANC importer: utilities to fetch skeletons/meshes and prepare curation TSVs
for the FlyWire Codex BANC dataset.

Notes
- This mirrors patterns from flywire_import.py, MANC_import.py, and OL_import.py
- No secrets or hardcoded paths: all I/O is parameterized
- Transform to template is optional and parameterized (defaults to no transform)

Dependencies: fafbseg (flywire), navis, flybrains, pandas
"""
from __future__ import annotations

import os
import glob
from typing import Iterable, List, Optional

import pandas as pd
import navis
import flybrains  # for transforms (optional)
from fafbseg import flywire


class BANCImporter:
    """
    Importer for the BANC dataset on FlyWire Codex.

    Contract
    - Inputs: list of root IDs (ints), output base directory
    - Outputs: per-root folder with volume.swc, volume_man.obj (if available), volume.nrrd (optional)
    - Error modes: skip missing skeleton/mesh with warnings; continue processing
    - Success: files written, and a small summary DataFrame returned
    """

    def __init__(
        self,
        dataset: str = "banc",
        transform_source: Optional[str] = None,
        transform_target: Optional[str] = None,
        transform_via: Optional[str] = None,
    ) -> None:
        """
        Create a BANC importer.

        Parameters
        - dataset: dataset name for fafbseg.flywire (e.g., 'banc'). If None, library default is used.
        - transform_source/target/via: passed to navis.xform_brain if set.
          If transform_source is None, no transform is applied.
        """
        self.dataset = dataset
        self.transform_source = transform_source
        self.transform_target = transform_target
        self.transform_via = transform_via

    # ---------- Helpers ----------
    @staticmethod
    def _ensure_dir(path: str) -> None:
        os.makedirs(path, exist_ok=True)

    @staticmethod
    def _delete_volume_files(local_folder_path: str) -> None:
        if not local_folder_path.endswith(os.sep):
            local_folder_path += os.sep
        file_paths = glob.glob(f"{local_folder_path}volume*")
        file_paths += glob.glob(f"{local_folder_path}thumbnail*")
        for fp in file_paths:
            try:
                os.remove(fp)
            except Exception:
                pass

    def _maybe_transform(self, obj):
        if not self.transform_source:
            return obj
        return navis.xform_brain(
            obj,
            source=self.transform_source,
            target=self.transform_target,
            via=self.transform_via,
        )

    # ---------- Core fetch/write ----------
    def fetch_skeleton(self, root_id: int):
        return flywire.get_skeletons(root_id, dataset=self.dataset)

    def fetch_mesh(self, root_id: int, lod: Optional[int] = None):
        # For FlyWire/FAFB we used get_mesh_neuron; try same pattern for BANC
        return flywire.get_mesh_neuron(root_id, dataset=self.dataset, lod=lod)

    def write_artifacts_for_root(
        self,
        root_id: int,
        out_dir: str,
        redo: bool = False,
        voxelize_nrrd: bool = True,
        voxel_pitch: Optional[List[str]] = None,
    ) -> dict:
        """
        Fetch skeleton/mesh for a root and write swc/obj/nrrd into out_dir/root_id/.
        Returns a summary dict with file paths and status.
        """
        out_folder = os.path.join(out_dir, str(root_id))
        self._ensure_dir(out_folder)
        swc_path = os.path.join(out_folder, "volume.swc")
        obj_path = os.path.join(out_folder, "volume_man.obj")
        nrrd_path = os.path.join(out_folder, "volume.nrrd")

        summary = {"root_id": root_id, "swc": None, "obj": None, "nrrd": None, "warnings": []}

        if redo:
            self._delete_volume_files(out_folder)

        # Skeleton
        try:
            if redo or not os.path.exists(swc_path):
                skel = self.fetch_skeleton(root_id)
                skel_t = self._maybe_transform(skel)
                if not skel_t:
                    summary["warnings"].append("no_skeleton_after_transform")
                else:
                    navis.write_swc(skel_t, swc_path)
                    summary["swc"] = swc_path
        except Exception as e:
            summary["warnings"].append(f"skeleton_error:{e}")

        # Mesh
        mesh_obj = None
        try:
            if redo or not os.path.exists(obj_path):
                mesh = self.fetch_mesh(root_id)
                mesh_t = self._maybe_transform(mesh)
                if not mesh_t:
                    summary["warnings"].append("no_mesh_after_transform")
                else:
                    navis.write_mesh(mesh_t, obj_path)
                    summary["obj"] = obj_path
                    mesh_obj = mesh_t
        except Exception as e:
            summary["warnings"].append(f"mesh_error:{e}")

        # NRRD via voxelization of mesh (fallback to skeleton if mesh missing)
        try:
            if voxelize_nrrd and (redo or not os.path.exists(nrrd_path)):
                src = mesh_obj
                if src is None:
                    # Try skeleton if mesh unavailable
                    try:
                        if "no_skeleton_after_transform" not in summary["warnings"] and os.path.exists(swc_path):
                            src = navis.read_swc(swc_path)
                    except Exception:
                        src = None
                if src is None:
                    summary["warnings"].append("no_source_for_nrrd")
                else:
                    pitch = voxel_pitch or ["0.5 microns", "0.5 microns", "1.0 microns"]
                    vx = navis.voxelize(src, pitch=pitch, parallel=True)
                    vx.grid = (vx.grid).astype("uint8") * 255
                    navis.write_nrrd(vx, filepath=nrrd_path, compression_level=9)
                    summary["nrrd"] = nrrd_path
        except Exception as e:
            summary["warnings"].append(f"nrrd_error:{e}")

        return summary

    # ---------- Batch ----------
    def process_batch(
        self,
        root_ids: Iterable[int],
        out_dir: str,
        redo: bool = False,
        voxelize_nrrd: bool = True,
        voxel_pitch: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Process multiple roots; returns a summary DataFrame for all roots.
        """
        results = []
        total = len(list(root_ids)) if not isinstance(root_ids, list) else len(root_ids)
        if not isinstance(root_ids, list):
            root_ids = list(root_ids)
        for idx, rid in enumerate(root_ids, start=1):
            print(f"[BANC] Processing {idx}/{total}: {rid}")
            res = self.write_artifacts_for_root(
                rid, out_dir=out_dir, redo=redo, voxelize_nrrd=voxelize_nrrd, voxel_pitch=voxel_pitch
            )
            results.append(res)
        return pd.DataFrame(results)


def generate_curation_tsv_from_ids(root_ids: Iterable[int], label_prefix: str = "BANC:") -> pd.DataFrame:
    """
    Minimal curation TSV given a list of BANC root IDs.
    When richer metadata is available, extend this similar to MANC/OL generators.
    """
    df = pd.DataFrame({"filename": list(root_ids)})
    df["is_a"] = "adult neuron"
    df["part_of"] = "adult brain"
    df["label"] = label_prefix + df["filename"].astype(str)
    df["comment"] = ""
    df["dbxrefs"] = "flywire_banc:" + df["filename"].astype(str)
    return df[["filename", "is_a", "part_of", "label", "comment", "dbxrefs"]]


__all__ = ["BANCImporter", "generate_curation_tsv_from_ids"]
