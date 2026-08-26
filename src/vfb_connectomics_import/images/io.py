"""The served-file half of the BANC image loader: what gets written, swapped and deleted.

Split out from `banc_image_loader.py` on purpose. Everything here can **destroy a served
image**, and none of it needs the network, navis, or a transform — so it is the part worth
reading closely and the part that can be unit-tested outright. The loader keeps the
fetching, geometry and orchestration; this module owns the filesystem contract.

The contract, in one paragraph
------------------------------
A neuron's image is a set of files in one folder. A rebuild writes the **complete** new set
to `volume.partial.*` first, then swaps each file into place with `os.replace`, which is
atomic and overwrites — so a served file goes straight from old to new and is never briefly
absent. Nothing is deleted before the replacement exists. If the rebuild fails or the
process is killed, the partials are discarded and the old image keeps serving. Deletion
happens in exactly two places: sweeping files left over from a previous alignment *after* a
successful swap, and `remove_all()` for an image the rebuild has positively shown to be
spurious.

See ISSUES.md IMG-3 (spurious wrong-template images) and the `banc_image_loader` docstring.
"""
import glob
import json
import os
import shutil

#: product key -> served filename. The keys are what `--products` accepts.
PRODUCTS = {'swc': 'volume.swc', 'obj': 'volume_man.obj', 'nrrd': 'volume.nrrd'}

#: Globs for everything this loader considers "the served image". Thumbnails are included
#: because a thumbnail depicts the OLD alignment: leaving one beside a replaced volume is a
#: silently stale image.
SERVED_GLOBS = ('volume*', 'thumbnail*')

#: Statuses meaning "this neuron has been dealt with; do not redo it on resume".
#: 'error' is deliberately absent — errors must be retried.
TERMINAL = frozenset({'replaced', 'created', 'deleted_spurious', 'skipped',
                      'empty_here', 'too_small', 'no_source', 'nothing_to_write'})


def partial_path(path):
    """Where an in-progress write goes.

    The suffix goes BEFORE the extension (`volume.partial.swc`, not `volume.swc.partial`)
    because navis picks its writer from the extension and treats an unrecognised one as a
    folder path, failing with "Parent folder ... must exist".
    """
    base, ext = os.path.splitext(path)
    return f'{base}.partial{ext}'


class OutputSet:
    """The served files for one neuron in one template folder.

    `products` is the subset of `PRODUCTS` this run is responsible for. Files outside that
    subset are still swept after a successful swap — a product dropped from `--products`
    would otherwise linger from the previous alignment.
    """

    def __init__(self, folder, products):
        self.folder = folder
        self.products = [k for k in PRODUCTS if k in products]
        self.paths = {k: os.path.join(folder, PRODUCTS[k]) for k in self.products}

    # -- inspection ---------------------------------------------------------------
    def served(self):
        """Absolute paths of every served file currently in the folder."""
        out = []
        for g in SERVED_GLOBS:
            out += glob.glob(os.path.join(self.folder, g))
        return sorted(p for p in out if '.partial.' not in os.path.basename(p))

    def existing_volumes(self):
        """Served `volume*` files only.

        Used to decide `replaced` vs `created`. A stray thumbnail with no volume beside it
        is not an image, so it must not make a fresh write report itself as a replacement.
        """
        return sorted(p for p in self.served()
                      if os.path.basename(p).startswith('volume'))

    def complete(self):
        """True when every product this run wants is already present."""
        return bool(self.paths) and all(os.path.exists(p) for p in self.paths.values())

    # -- mutation -----------------------------------------------------------------
    def clear_partials(self):
        """Discard in-progress writes left by a killed run. Safe to call at any time:
        a `.partial.*` file is by definition not being served."""
        for p in glob.glob(os.path.join(self.folder, '*.partial.*')):
            _unlink(p)

    def swap(self, built):
        """Atomically move `built` ({partial path: final path}) into place, then sweep.

        Returns (wrote, removed) as basename lists. `os.replace` overwrites, so there is
        no delete-then-write step and no window in which a served file is missing.
        """
        wrote = []
        for tmp, final in built.items():
            os.replace(tmp, final)
            wrote.append(os.path.basename(final))
        removed = self._sweep(keep=set(built.values()))
        return sorted(wrote), removed

    def archive_to(self, dest):
        """**Copy** (never move) the current served files to `dest`. Returns basenames.

        A copy, so the live folder keeps serving untouched until the atomic swap. This is
        the only way to keep the pre-replacement image for comparison: after the swap the
        old bytes are gone, and archiving into the live folder would publish clutter.
        """
        files = self.served()
        if not files:
            return []
        os.makedirs(dest, exist_ok=True)
        out = []
        for p in files:
            try:
                shutil.copy2(p, os.path.join(dest, os.path.basename(p)))
                out.append(os.path.basename(p))
            except Exception:
                pass
        return sorted(out)

    def remove_all(self):
        """Delete the whole served image. Only for an image the rebuild has positively
        shown to be spurious — never on absent or failed input."""
        return self._sweep(keep=())

    def _sweep(self, keep=()):
        keep = set(keep)
        removed = []
        for p in self.served():
            if p in keep:
                continue
            if _unlink(p):
                removed.append(os.path.basename(p))
        return sorted(removed)


def _unlink(path):
    try:
        os.remove(path)
        return True
    except Exception:
        return False


class Ledger:
    """Append-only JSONL record of neurons that reached a terminal state.

    This is the only usable progress marker for a replace run: nearly every neuron already
    has files on disk, so file existence cannot tell you where you got to. Written one
    flushed line at a time so it survives `kill -9`.
    """

    FIELDS = ('root', 'region', 'status', 'swc_source')

    def __init__(self, path):
        self.path = path
        self._fh = None

    def done(self):
        """{(root, region)} already finished. Empty if there is no ledger yet."""
        out = set()
        if not self.path or not os.path.exists(self.path):
            return out
        with open(self.path) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue          # a torn final line is expected after a kill
                if d.get('status') in TERMINAL:
                    out.add((str(d.get('root')), d.get('region')))
        return out

    def record(self, rec):
        if not self.path:
            return
        if self._fh is None:
            self._fh = open(self.path, 'a')
        self._fh.write(json.dumps({k: rec.get(k) for k in self.FIELDS}) + '\n')
        self._fh.flush()

    def close(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
