"""Where each connectome's geometry comes from, and in which space it arrives.

One class per dataset. Everything here returns coordinates in the connectome's declared
`space`/`units` from `connectomes.py`, so the cut planes and baked fields apply without
per-caller conversion — getting that wrong is silent and produces plausible garbage.

Both current sources are **anonymous HTTPS** against public Google Storage: no token, no
`caveclient`, no `neuprint-python`. That last point is load-bearing — the images extra
must stay installable on the Jenkins node's Python 3.9, and neuprint-python needs 3.10+.

`use_https=True` is mandatory on every CloudVolume. Without it cloudvolume falls through
to google-cloud-python and dies with DefaultCredentialsError on any machine without
application-default credentials, i.e. on every build agent.
"""
import io
import os
import urllib.request

import numpy as np


def _get(url, timeout=300):
    return urllib.request.urlopen(url, timeout=timeout).read()


def _cloudvolume(path):
    from cloudvolume import CloudVolume
    return CloudVolume(path, use_https=True, progress=False)


class Source:
    """Interface: skeleton() -> (n,7) SWC-like array, mesh() -> trimesh, both in source units."""
    space = None

    def skeleton(self, ident):
        raise NotImplementedError

    def mesh(self, ident, lod=0):
        raise NotImplementedError


# --------------------------------------------------------------------------------- BANC
class BancBucket(Source):
    """BANC v888, gs://lee-lab_brain-and-nerve-cord-fly-connectome. Coordinates in BANC nm.

    Skeleton preference is the loader's business (published `_skeleton`, else skeletonise
    the mesh, else the 125x-coarser `_l2`); this only fetches what it is asked for.
    """
    space = 'BANC'
    BUCKET = 'lee-lab_brain-and-nerve-cord-fly-connectome'
    SWC_PREFIX = 'compiled_data/banc_888/banc_banc_space_swc'
    MESH_LAYER = 'neuron_meshes'

    def __init__(self, skeleton_dir=None):
        self.skeleton_dir = skeleton_dir
        self._cv = None

    def swc(self, ident, suffix='skeleton'):
        """`<root>_{skeleton,l2}.swc` as a raw SWC array (BANC nm; radius nm). None if absent."""
        name = f'{ident}_{suffix}.swc'
        if self.skeleton_dir:
            p = os.path.join(self.skeleton_dir, name)
            if not os.path.exists(p):
                return None            # a staged dir is authoritative: no bucket fallback
            raw = open(p).read()
        else:
            try:
                raw = _get(f'https://storage.googleapis.com/{self.BUCKET}/'
                           f'{self.SWC_PREFIX}/{name}').decode()
            except Exception:
                return None
        arr = np.loadtxt(io.StringIO(raw), comments='#', ndmin=2)
        return arr if len(arr) > 1 else None

    def skeleton(self, ident):
        return self.swc(ident, 'skeleton')

    def mesh(self, ident, lod=0):
        """BANC publishes LOD 0 only, so `lod` is accepted and ignored."""
        import trimesh
        if self._cv is None:
            self._cv = _cloudvolume(f'precomputed://gs://{self.BUCKET}/{self.MESH_LAYER}')
        try:
            m = self._cv.mesh.get(int(ident))
        except Exception:
            return None                # genuinely absent upstream; coverage is 94.4%/68.8%
        mm = m[int(ident)] if isinstance(m, dict) else m
        return trimesh.Trimesh(vertices=np.asarray(mm.vertices, np.float64),
                               faces=np.asarray(mm.faces, np.int64), process=False)


# ------------------------------------------------------------------------------- maleCNS
class MaleCnsBucket(Source):
    """male-CNS v1.0, gs://flyem-male-cns/v1.0/segmentation. Coordinates in JRCFIB2022M nm.

    THREE geometry products, in TWO coordinate spaces — verified 2026-08-28:

      multi-res-meshes                       nanometres    multi-LOD draco, lod 0..3
      skeletons-precomputed/<id>             nanometres    binary, NO radius attribute
      skeletons-swc/<id>.swc                 8 nm VOXELS   NeuTu, has radius (nm)
      skeletons-highres-swc/<id>.swc         8 nm VOXELS   ~20x denser, 115 GB total

    So an SWC must be multiplied by 8 to sit in the same space as everything else. This
    module does that conversion, and `skeleton()` always returns nanometres.

    Coverage: 211,573 SWC / 211,574 precomputed, against 166,701 v1.0 neurons in VFB —
    the bucket covers more segments than we import, not fewer.
    """
    space = 'JRCFIB2022M'
    BUCKET = 'flyem-male-cns'
    LAYER = 'v1.0/segmentation'
    VOXEL_NM = 8.0

    def __init__(self, skeleton_dir=None, swc_variant='skeletons-swc'):
        self.skeleton_dir = skeleton_dir
        self.swc_variant = swc_variant
        self._cv = None

    def _url(self, sub):
        return f'https://storage.googleapis.com/{self.BUCKET}/{self.LAYER}/{sub}'

    def skeleton_precomputed(self, ident):
        """(n,3) nm vertex array + (m,2) edges. No radius — the format carries none here."""
        try:
            raw = _get(self._url(f'skeletons-malecns/skeletons-precomputed/{ident}'))
        except Exception:
            return None, None
        nv, ne = np.frombuffer(raw, np.uint32, 2)
        v = np.frombuffer(raw, np.float32, 3 * int(nv), 8).reshape(int(nv), 3).astype(float)
        e = np.frombuffer(raw, np.uint32, 2 * int(ne), 8 + 12 * int(nv)).reshape(int(ne), 2)
        return v, e

    def skeleton(self, ident):
        """SWC array in NANOMETRES (xyz scaled from 8 nm voxels; radius already nm)."""
        name = f'{ident}.swc'
        if self.skeleton_dir:
            p = os.path.join(self.skeleton_dir, name)
            if not os.path.exists(p):
                return None
            raw = open(p).read()
        else:
            try:
                raw = _get(self._url(f'skeletons-malecns/{self.swc_variant}/{name}')).decode()
            except Exception:
                return None
        arr = np.loadtxt(io.StringIO(raw), comments='#', ndmin=2)
        if len(arr) < 2:
            return None
        arr = arr.astype(float)
        arr[:, 2:5] *= self.VOXEL_NM        # 8 nm voxels -> nm; radius column is already nm
        return arr

    def mesh(self, ident, lod=0):
        """Multi-LOD. lod0 ~198 faces/um2; each step is roughly a 7x reduction."""
        import trimesh
        if self._cv is None:
            self._cv = _cloudvolume(f'precomputed://gs://{self.BUCKET}/{self.LAYER}')
        try:
            m = self._cv.mesh.get(int(ident), lod=lod)
        except Exception:
            return None
        mm = m[int(ident)] if isinstance(m, dict) else m
        return trimesh.Trimesh(vertices=np.asarray(mm.vertices, np.float64),
                               faces=np.asarray(mm.faces, np.int64), process=False)


SOURCES = {'banc': BancBucket, 'malecns': MaleCnsBucket}


def for_connectome(cid, **kw):
    return SOURCES[cid](**kw)
