"""Register pre-baked BANC->template transforms with navis, replacing the elastix legs.

Why this exists
---------------
BANC's registrations are published as elastix B-spline parameter files, so every transform
shells out to the `transformix` binary: ~0.35 s of process spawn per call plus ~9.8 us per
point. On a 598k-vertex mesh that is 5.9 s, of which 92% is the elastix hop. At v888's
scale that is hundreds of hours.

The JRC legs of the same chain are already distributed as dense deformation fields (the
`.h5` files in ~/flybrain-data). This module supplies the missing equivalent for the BANC
legs: the elastix hop sampled onto a regular grid, memory-mapped and interpolated in numpy.

Measured against the exact elastix chain: 5.5-13.7 nm mean error, max 75 nm — against an
8 nm source voxel and a ~520 nm template voxel. 0.2-0.35 us per point, ~30x faster end to
end and with no binary dependency.

Only the elastix hop is baked. The remaining H5 hops stay as navis' own transforms, so
these compose normally and are reusable for any downstream target.

Usage
-----
    from vfb_connectomics_import.images import transforms as banc_baked
    transforms.register()                      # once per process
    navis.xform_brain(pts, source='BANC', target='JRC2018U')

Field location, in order of precedence:
    transforms.register(field_dir='...')
    $BANC_FIELD_DIR
    ~/Documents/banc_transform_fields

Building the fields: see `bake_fields.py`. They are ~543 MB and must NOT be committed;
publish them alongside VFB's other transforms (flybrains already consumes those via
`flybrains.download_vfb_transforms`).
"""
import json
import os

import numpy as np
from scipy.ndimage import map_coordinates

import navis
from navis.transforms import FunctionTransform

BUILTIN_FIELD_DIR = os.path.expanduser('~/Documents/banc_transform_fields')

#: Resolved at import for backwards compatibility. Prefer `resolve_field_dir()`, which
#: reads the environment at call time — a Jenkins job that sets `$BANC_FIELD_DIR` after
#: this module is imported would otherwise be silently ignored.
DEFAULT_FIELD_DIR = os.environ.get('BANC_FIELD_DIR', BUILTIN_FIELD_DIR)

#: baked file -> the space it maps BANC into (the elastix hop only), and the template the
#: pipeline actually targets downstream. `final` is what `assert_baked_path` checks, since
#: that is the route the loaders use.
FIELDS = {
    'brain': dict(stem='banc_brain_2um', target='JRC2018F',    final='JRC2018U'),
    'vnc':   dict(stem='banc_vnc_2um',   target='JRCVNC2018F', final='JRCVNC2018U'),
}

_cache = {}


class MissingFieldsError(RuntimeError):
    """The baked fields are not where they were expected.

    Raised rather than warned because the fallback is silent and expensive: navis simply
    routes through the elastix edges instead, which either dies with an error that
    `except Exception` cannot catch (docs/ISSUES.md CODE-2) or, if transformix happens to be
    on the agent, quietly runs ~30x slower and produces correct-looking output.
    """


def resolve_field_dir(field_dir=None):
    """Where the fields should be, and which of the three sources decided that.

    Returning the provenance matters in CI: 'built-in default' in a Jenkins log is the
    tell that `$BANC_FIELD_DIR` was never set on the agent.
    """
    if field_dir:
        return field_dir, 'field_dir argument'
    env = os.environ.get('BANC_FIELD_DIR')
    if env:
        return env, '$BANC_FIELD_DIR'
    return BUILTIN_FIELD_DIR, 'built-in default (a developer path — not valid in CI)'


def missing_fields(field_dir=None):
    """Expected-but-absent field files, as {tag: path}."""
    d, _ = resolve_field_dir(field_dir)
    out = {}
    for tag, cfg in FIELDS.items():
        p = os.path.join(d, cfg['stem'] + '.npy')
        if not os.path.exists(p):
            out[tag] = p
    return out


def _missing_error(field_dir=None):
    d, how = resolve_field_dir(field_dir)
    absent = missing_fields(field_dir)
    return MissingFieldsError(
        f'baked BANC fields not found.\n'
        f'  looked in : {d}\n'
        f'  chosen by : {how}\n'
        f'  missing   : ' + ', '.join(f'{t} -> {p}' for t, p in absent.items()) + '\n'
        f'  fix       : set $BANC_FIELD_DIR to the directory holding '
        f'{", ".join(c["stem"] + ".npy" for c in FIELDS.values())}, or build them with '
        f'images/bake_fields.py. Falling back to elastix is NOT safe here — see '
        f'docs/TRANSFORMS.md and docs/ISSUES.md CODE-2.')


class BakedField:
    """BANC nanometres -> template microns by trilinear lookup on a memmapped grid.

    Returns NaN outside the grid. This matters: `map_coordinates(mode='nearest')` clamps
    to the edge instead, which silently produced 51 um errors that then *passed* a
    bounding-box check. Out-of-domain has to fail loudly.
    """

    def __init__(self, npy_path, mmap=True):
        meta_path = os.path.splitext(npy_path)[0] + '.json'
        self.meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        self.field = np.load(npy_path, mmap_mode='r' if mmap else None)
        self.lo = np.asarray(self.meta.get('lo'), float)
        self.step = np.asarray(self.meta.get('step'), float)
        self.target = self.meta.get('target')
        self.shape = np.asarray(self.field.shape[:3])
        self.hi = self.lo + (self.shape - 1) * self.step
        self.path = npy_path
        if list(self.field.shape) != list(self.meta.get('shape', self.field.shape)):
            raise ValueError(f'{npy_path}: array shape {self.field.shape} does not match '
                             f'metadata {self.meta.get("shape")} — truncated field?')

    def __repr__(self):
        return (f'<BakedField {os.path.basename(self.path)} -> {self.target}, '
                f'grid {tuple(int(n) for n in self.shape)} @ {self.step[0]:.0f} nm>')   # int(): numpy 2 reprs bare scalars as np.int64(445)

    def __call__(self, pts):
        pts = np.asarray(pts, float)
        out = np.full(pts.shape, np.nan)
        ok = np.all((pts >= self.lo) & (pts <= self.hi), axis=1)
        if ok.any():
            idx = ((pts[ok] - self.lo) / self.step).T
            out[ok] = np.stack(
                [map_coordinates(self.field[..., k], idx, order=1, mode='nearest')
                 for k in range(3)], -1)
        return out

    def in_domain(self, pts):
        pts = np.asarray(pts, float)
        return np.all((pts >= self.lo) & (pts <= self.hi), axis=1)


def load(field_dir=None, mmap=True):
    """Load (and cache) the baked fields. Memmapped by default.

    Memmapping matters for parallel workers: the OS page cache serves every reader from
    one set of physical pages, so N workers share ~543 MB rather than each holding a copy.
    Contrast `H5transform.full_ingest()`, which is ~4.6 GB resident per process — and h5py
    is not fork-safe.
    """
    d, _ = resolve_field_dir(field_dir)
    out = {}
    for tag, cfg in FIELDS.items():
        p = os.path.join(d, cfg['stem'] + '.npy')
        if not os.path.exists(p):
            continue
        if p not in _cache:
            _cache[p] = BakedField(p, mmap=mmap)
        bf = _cache[p]
        if bf.target != cfg['target']:
            raise ValueError(
                f'{p}: sidecar json says target={bf.target!r} but this file is registered '
                f'as the {tag} field, which must map BANC -> {cfg["target"]!r}. The two '
                f'fields have probably been swapped or rebuilt against the wrong target.')
        out[tag] = bf
    return out


def assert_baked_path(verbose=True):
    """Assert the baked edges actually win the path search, for the real pipeline targets.

    This is the end-to-end check: fields on disk are necessary but not sufficient, because
    `register()` could have been skipped, the weight could have been outgunned, or a caller
    could have passed `via=`/`avoid=` (which bypass weighting entirely — docs/TRANSFORMS.md).
    An `ElastixTransform` surviving in the path means the bake is not being used.
    """
    problems = []
    for tag, cfg in FIELDS.items():
        for tgt in (cfg['target'], cfg['final']):
            path, trs = navis.transforms.registry.find_bridging_path('BANC', tgt)
            names = [type(x).__name__ for x in trs]
            if any('Elastix' in n for n in names):
                problems.append(f'{tag} -> {tgt}: {" -> ".join(path)}  ({", ".join(names)})')
            elif verbose:
                print(f'banc_baked path {tag} -> {tgt:12s}: {" -> ".join(path)}')
    if problems:
        raise RuntimeError(
            'banc_baked: elastix is still in the transform path, so the baked fields are '
            'NOT being used:\n  ' + '\n  '.join(problems) +
            '\n  Did register() run? Do not pass via=/avoid= for a BANC source.')
    return True


def register(weight=0.1, field_dir=None, mmap=True, verbose=True, required=True):
    """Add the baked fields to navis' registry, preferred over the elastix transforms.

    The registry graph is a MultiDiGraph, so these sit alongside the elastix edges rather
    than replacing them; `weight` below 1 makes `nx.shortest_path` choose them. The elastix
    transforms remain available as a fallback and for verification.

    Note `xform_brain(via=...)`/`avoid=...` bypass weighting entirely (navis uses
    `all_simple_paths` and takes the first match), so a baked edge is ignored if either is
    passed. Do not use them for a BANC source — the unrouted path is already correct.

    `required=True` (the default) raises `MissingFieldsError` if any expected field is
    absent. This defaults to strict on purpose: the previous behaviour printed a warning
    and returned `{}`, which in a batch job is indistinguishable from success.
    Pass `required=False` only for interactive use where the elastix fallback is wanted.
    """
    absent = missing_fields(field_dir)
    if absent and required:
        raise _missing_error(field_dir)
    fields = load(field_dir=field_dir, mmap=mmap)
    if not fields and verbose:
        d, how = resolve_field_dir(field_dir)
        print(f'banc_baked: no fields found in {d} (chosen by {how}); '
              f'falling back to elastix (needs transformix on PATH)')
    for tag, bf in fields.items():
        navis.transforms.registry.register_transform(
            transform=FunctionTransform(bf),
            source='BANC', target=bf.target,
            transform_type='bridging', weight=weight)
        if verbose:
            print(f'banc_baked: BANC -> {bf.target:12s} weight={weight}  {bf}')
    navis.transforms.registry.clear_caches()
    return fields


def self_check(field_dir=None, verbose=True, check_path=True):
    """Verify the expected fields are present, load, and reject out-of-domain points.

    Run this at job startup: a truncated, mismatched or absent field would otherwise fail
    silently across tens of thousands of neurons.

    This asserts the *expected* field set rather than iterating whatever `load()` happened
    to find. The earlier version did the latter, so with zero fields on disk it found no
    problems and returned True — passing vacuously in exactly the case it existed to catch.
    """
    absent = missing_fields(field_dir)
    if absent:
        raise _missing_error(field_dir)
    fields = load(field_dir=field_dir)
    problems = []
    for tag in FIELDS:
        if tag not in fields:
            problems.append(f'{tag}: expected field did not load')
    for tag, bf in fields.items():
        inside = bf.lo + (bf.hi - bf.lo) / 2
        outside = bf.hi + 10 * bf.step
        got_in = bf(inside[None, :])[0]
        got_out = bf(outside[None, :])[0]
        if np.isnan(got_in).any():
            problems.append(f'{tag}: grid centre returned NaN')
        if not np.isnan(got_out).all():
            problems.append(f'{tag}: point outside the grid was NOT rejected '
                            f'(got {got_out}) — clamping is active, results will be wrong')
        if verbose:
            print(f'banc_baked self-check {tag}: centre -> {np.round(got_in, 2)}, '
                  f'outside -> {"NaN (ok)" if np.isnan(got_out).all() else "NOT REJECTED"}')
    if problems:
        raise RuntimeError('banc_baked self-check failed:\n  ' + '\n  '.join(problems))
    if check_path:
        assert_baked_path(verbose=verbose)
    return True
