#!/usr/bin/env python
"""Tests for the BANC image loader's safety rules. No network, no navis, no transforms.

    python -m pytest tests/test_images.py -v
    python tests/test_images.py                 # same, without pytest

These exist because the loader can destroy served images, and the rules governing when it
does are the part worth pinning down. Every test here is about *policy* and *filesystem
contract*, which is exactly the half that needs no heavy dependencies. The geometry and
transform half is covered by running the loader against real neurons.

Verified by hand on 2026-08-25/26 before being written down here; these are the same cases.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from vfb_connectomics_import.images.io import (
    PRODUCTS, SWEEP_AFTER_SWAP, TERMINAL, Ledger, OutputSet, partial_path)

ALL = ('swc', 'obj', 'nrrd')


# --------------------------------------------------------------------------- helpers
#: What VFB actually serves per neuron, confirmed live 2026-08-26. Only the first three
#: are written by this loader; the rest belong to other jobs.
SERVED = ('volume.swc', 'volume.nrrd', 'volume_man.obj',
          'volume.obj', 'volume.wlz', 'volume.dps.pkl',
          'thumbnail.png', 'thumbnailT.png')


def plant(folder, thumbnail=True, volumes=ALL, extras=True):
    """An existing v626-era image, as the loader will find on almost every neuron."""
    os.makedirs(folder, exist_ok=True)
    for k in volumes:
        with open(os.path.join(folder, PRODUCTS[k]), 'w') as fh:
            fh.write(f'OLD v626 {k}')
    if extras:
        for n in ('volume.obj', 'volume.wlz', 'volume.dps.pkl'):
            with open(os.path.join(folder, n), 'w') as fh:
                fh.write('OLD ' + n)
    if thumbnail:
        for n in ('thumbnail.png', 'thumbnailT.png'):
            with open(os.path.join(folder, n), 'w') as fh:
                fh.write('OLD THUMB')


def names(folder):
    return sorted(os.listdir(folder))


def read(folder, kind):
    with open(os.path.join(folder, PRODUCTS[kind])) as fh:
        return fh.read()


def build(out, kinds, text='NEW'):
    """Write partials as a real rebuild would, returning {partial: final}."""
    built = {}
    for k in kinds:
        tmp = partial_path(out.paths[k])
        with open(tmp, 'w') as fh:
            fh.write(f'{text} {k}')
        built[tmp] = out.paths[k]
    return built


# ------------------------------------------------------------------- partial path naming
def test_partial_suffix_precedes_the_extension():
    """navis picks its writer from the extension and treats an unknown one as a folder,
    failing with "Parent folder ... must exist". This bit once and must not regress."""
    assert partial_path('/x/volume.swc') == '/x/volume.partial.swc'
    assert partial_path('/x/volume_man.obj') == '/x/volume_man.partial.obj'
    assert not partial_path('/x/volume.nrrd').endswith('.partial')


# ------------------------------------------------------------------------ the swap is safe
def test_swap_replaces_three_products_and_deletes_only_volume_obj():
    """The agreed contract (2026-08-26): replace swc / nrrd / volume_man.obj, additionally
    delete volume.obj, and LEAVE volume.wlz and the thumbnails. Those go briefly out of
    sync with the new alignment, which is accepted -- other jobs refresh them, and
    deleting products nothing here regenerates would be worse."""
    with tempfile.TemporaryDirectory() as d:
        plant(d)
        out = OutputSet(d, ALL)
        assert read(d, 'swc') == 'OLD v626 swc'
        wrote, removed = out.swap(build(out, ALL))
        assert wrote == sorted(PRODUCTS[k] for k in ALL)
        assert removed == ['volume.dps.pkl', 'volume.obj'], removed
        assert read(d, 'swc') == 'NEW swc'
        for n in ('volume.wlz', 'thumbnail.png', 'thumbnailT.png'):
            assert n in names(d), n + ' must NOT be swept'


def test_sweep_list_is_exactly_volume_obj_and_dps():
    """Pinned in both directions. An earlier version globbed volume*/thumbnail* and removed
    8 files per neuron including volume.wlz, which nothing here regenerates. A later one
    swept only volume.obj and left volume.dps.pkl stale — which NBLAST then reads as
    unchanged, so its combined cache keeps the old shape forever."""
    assert SWEEP_AFTER_SWAP == ('volume.obj', 'volume.dps.pkl')


def test_swap_never_leaves_a_served_file_missing():
    """os.replace overwrites, so there is no delete-then-write window. Assert the final
    files exist continuously by checking none were absent at any observable point."""
    with tempfile.TemporaryDirectory() as d:
        plant(d, thumbnail=False)
        out = OutputSet(d, ALL)
        built = build(out, ALL)
        for k in ALL:                       # still the OLD file, before the swap
            assert os.path.exists(out.paths[k])
        out.swap(built)
        for k in ALL:
            assert os.path.exists(out.paths[k])
        assert not [f for f in names(d) if 'partial' in f]


def test_swap_sweeps_a_product_dropped_from_products():
    """Running with --products swc,nrrd must not leave last alignment's OBJ behind."""
    with tempfile.TemporaryDirectory() as d:
        plant(d, thumbnail=False)
        out = OutputSet(d, ('swc', 'nrrd'))
        _, removed = out.swap(build(out, ('swc', 'nrrd')))
        assert removed == ['volume.dps.pkl', 'volume.obj', 'volume_man.obj'], removed
        assert 'volume.wlz' in names(d), 'still not ours to delete'


# ------------------------------------------------------------- existing-image bookkeeping
def test_a_stray_thumbnail_is_not_an_image():
    """had_image drives 'replaced' vs 'created'. A thumbnail with no volume beside it must
    not make a fresh write report itself as a replacement."""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'thumbnail.png'), 'w') as fh:
            fh.write('x')
        out = OutputSet(d, ALL)
        assert out.served(), 'the thumbnail is a served file'
        assert not out.existing_volumes(), 'but it is not an image'


def test_complete_only_counts_requested_products():
    with tempfile.TemporaryDirectory() as d:
        plant(d, thumbnail=False, volumes=('swc',))
        assert OutputSet(d, ('swc',)).complete()
        assert not OutputSet(d, ALL).complete()


def test_clear_partials_leaves_served_files_alone():
    with tempfile.TemporaryDirectory() as d:
        plant(d)
        out = OutputSet(d, ALL)
        build(out, ALL)                       # leave partials lying around
        assert [f for f in names(d) if 'partial' in f]
        out.clear_partials()
        assert not [f for f in names(d) if 'partial' in f]
        assert read(d, 'swc') == 'OLD v626 swc', 'the old image must survive'


def test_remove_all_clears_volumes_and_thumbnails():
    with tempfile.TemporaryDirectory() as d:
        plant(d)
        removed = OutputSet(d, ALL).remove_all()
        assert sorted(removed) == sorted(SERVED), removed
        assert names(d) == [], 'a spurious image must not be left half-served'


# --------------------------------------------------------------------- the deletion policy
def _decide(sources_usable, empty, nodes, faces, had_image, delete_spurious=True,
            min_nodes=10, min_faces=100):
    """Call decide() without importing navis, by faking the two objects it reads."""
    from vfb_connectomics_import.images import loader as L

    class S:
        usable = sources_usable

    class H:
        pass
    h = H()
    h.empty, h.nodes, h.faces = empty, nodes, faces
    st = L.Settings(min_nodes=min_nodes, min_faces=min_faces,
                    delete_spurious=delete_spurious)
    return L.decide(S(), h, had_image, st)


def test_no_source_never_deletes():
    """THE safety rule. Upstream mesh coverage is 94.4%/68.8%, so absent input must never
    destroy a good image — a transient fetch failure would otherwise be permanent."""
    from vfb_connectomics_import.images import loader as L
    action, status, note = _decide(False, True, 0, 0, had_image=True)
    assert action == L.KEEP
    assert status == 'no_source'
    assert 'left untouched' in note


def test_empty_region_with_a_source_deletes_a_spurious_image():
    """ISSUES.md IMG-3: the ~4,660 wrong-template images. This is the only thing that
    ever cleans them up."""
    from vfb_connectomics_import.images import loader as L
    action, status, _ = _decide(True, True, 0, 0, had_image=True)
    assert action == L.DELETE
    assert status == 'deleted_spurious'


def test_empty_region_with_nothing_there_writes_nothing():
    from vfb_connectomics_import.images import loader as L
    action, status, _ = _decide(True, True, 0, 0, had_image=False)
    assert action == L.KEEP
    assert status == 'empty_here'


def test_no_delete_spurious_keeps_the_old_image():
    from vfb_connectomics_import.images import loader as L
    action, status, note = _decide(True, True, 0, 0, had_image=True,
                                   delete_spurious=False)
    assert action == L.KEEP
    assert status == 'empty_here'
    assert 'left in place' in note


def test_immaterial_region_is_treated_as_spurious():
    """A VNC half really did survive the bbox trim with 5 nodes / 36 faces — a truncated
    tip at the cut plane, not a depictable arbor."""
    from vfb_connectomics_import.images import loader as L
    action, status, note = _decide(True, False, 5, 36, had_image=True)
    assert action == L.DELETE
    assert status == 'deleted_spurious'
    assert '5 nodes / 36 faces' in note


def test_material_region_swaps():
    from vfb_connectomics_import.images import loader as L
    action, status, _ = _decide(True, False, 1825, 72769, had_image=True)
    assert action == L.SWAP
    assert status is None


def test_threshold_needs_both_to_be_below():
    """A big mesh with a tiny skeleton is still depictable, and vice versa."""
    from vfb_connectomics_import.images import loader as L
    assert _decide(True, False, 2, 5000, had_image=True)[0] == L.SWAP
    assert _decide(True, False, 500, 3, had_image=True)[0] == L.SWAP


# ------------------------------------------------------------------------------- ledger
def test_ledger_round_trip_and_error_retry():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'run.jsonl')
        with Ledger(p) as led:
            led.record(dict(root='1', region='brain', status='replaced',
                            swc_source='published_skeleton'))
            led.record(dict(root='2', region='brain', status='deleted_spurious',
                            swc_source='skeletonised_mesh'))
            led.record(dict(root='3', region='brain', status='error', swc_source='none'))
        done = Ledger(p).done()
        assert ('1', 'brain') in done
        assert ('2', 'brain') in done
        assert ('3', 'brain') not in done, 'errors must be retried, not skipped'


def test_ledger_survives_a_torn_final_line():
    """The point of flushing per line is surviving kill -9, which can tear the last one."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'run.jsonl')
        with open(p, 'w') as fh:
            fh.write('{"root": "1", "region": "brain", "status": "replaced"}\n')
            fh.write('{"root": "2", "regio')                 # killed mid-write
        assert Ledger(p).done() == {('1', 'brain')}


def test_ledger_absent_file_is_empty_not_an_error():
    assert Ledger('/nonexistent/nope.jsonl').done() == set()
    assert Ledger(None).done() == set()


def test_error_is_not_terminal():
    assert 'error' not in TERMINAL
    for s in ('replaced', 'created', 'deleted_spurious', 'no_source', 'empty_here',
              'too_small', 'skipped', 'nothing_to_write'):
        assert s in TERMINAL, s


# ----------------------------------------------------------------------------- geometry
def test_region_bounds_match_the_vfb_template_grids():
    """Read from the template NRRD headers on the VFB file server. The maleCNS script's
    constants (627.3695649, 293.1875965, 173) decode as exactly (grid - 1) * spacing."""
    from vfb_connectomics_import.images import loader as L
    brain = L.REGIONS['brain'].bounds
    assert abs(brain[0][1] - 627.3695649) < 1e-6
    assert abs(brain[1][1] - 293.1875965) < 1e-6
    assert abs(brain[2][1] - 173.0) < 1e-9
    vnc = L.REGIONS['vnc'].bounds
    assert [round(b[1], 4) for b in vnc] == [263.6, 515.6, 152.4]


def test_cut_keeps_the_right_side_of_the_neuropil_boundary():
    """brain y < 305,801; vnc y > 549,946. The 244 um of connective between them is
    dropped from both halves (ISSUES.md IMG-3)."""
    import numpy as np
    from vfb_connectomics_import.images import loader as L
    ys = [100_000, 305_800, 400_000, 549_947, 900_000]      # nm
    arr = np.zeros((len(ys), 7))
    arr[:, 3] = ys
    assert L.REGIONS['brain'].cut_swc(arr)[:, 3].tolist() == [100_000, 305_800]
    assert L.REGIONS['vnc'].cut_swc(arr)[:, 3].tolist() == [549_947, 900_000]
    kept = set(L.REGIONS['brain'].cut_swc(arr)[:, 3]) | set(L.REGIONS['vnc'].cut_swc(arr)[:, 3])
    assert 400_000 not in kept, 'connective material must be in neither half'


def test_to_url_round_trips_to_local():
    """The per-neuron console line is only useful if the link actually resolves."""
    from vfb_connectomics_import.images import loader as L
    url = 'http://www.virtualflybrain.org/data/VFB/i/0010/5soo/VFB_00101567/'
    for write_root in ('/IMAGE_WRITE/', '/IMAGE_WRITE', '/tmp/out/'):
        local = L.to_local(url, write_root)
        assert L.to_url(local, write_root) == url, write_root


def test_to_url_leaves_a_path_outside_write_root_alone():
    from vfb_connectomics_import.images import loader as L
    assert L.to_url('/somewhere/else/x', '/IMAGE_WRITE/') == '/somewhere/else/x'


def test_to_local_strips_either_vfb_url_scheme():
    from vfb_connectomics_import.images import loader as L
    for scheme in ('http', 'https'):
        got = L.to_local(f'{scheme}://www.virtualflybrain.org/data/VFB/i/0010/5soo/'
                         f'VFB_00101567/', '/IMAGE_WRITE/')
        assert got == '/IMAGE_WRITE/VFB/i/0010/5soo/VFB_00101567'


if __name__ == '__main__':
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith('test_') and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f'  PASS  {name}')
        except Exception as e:
            failed += 1
            print(f'  FAIL  {name}: {type(e).__name__}: {e}')
    print(f'\n{len(fns) - failed}/{len(fns)} passed')
    sys.exit(1 if failed else 0)
