# Rehearsing a destructive image run

`loader.py --mode replace` deletes a served image whenever the rebuild finds no depictable
material in a region. On maleCNS that is **~161,000 of the 333,402 image folders** — the
largest destructive operation this repo performs. This rehearses it against a local mirror
of what VFB serves today, so every destructive path runs for real with nothing at risk.

    bash tools/rehearsal/run.sh          # ~10 min for 80 neurons

Output goes to `$REHEARSAL_DIR` (default `~/Documents/vfb_malecns_rehearsal`), deliberately
**not** a scratch directory — an earlier rehearsal was lost when one was cleaned.

## Why the mirror is the point

Run the loader against an empty tree and `had_image` is False, so `decide()` can never
return DELETE, `--archive` copies nothing and the atomic swap degrades to a plain write.
Every path worth testing is skipped, and the run still looks like a success. `mirror_served.py`
downloads the real served files first so the rehearsal exercises deletion, archiving and
replacement as production would.

## The checks

`check.py` fails the run on any of:

1. a deleted channel whose files are not in the archive, or whose live folder still has some
2. a written channel missing a product, or still holding `volume.obj` / `volume.dps.pkl`
   (the sweep must remove those — a stale `dps` keeps NBLAST scoring the old shape forever)
3. any `.partial` file left behind
4. a named DN/AN crosser that did not write both halves — the check that catches a wrong cut
5. a neuron left with no image in any region
6. any error
7. an NRRD off the template grid, all-zero, or not uint8
8. an OBJ that does not parse, has no faces, or disagrees with the reported face count
9. anything served above the 200 f/µm² ceiling

Checks 7-9 exist because an earlier version asserted only that each product *file existed*.
A real `write_nrrd` bug (`region.spacing` where it should have been
`region.template.spacing`) passed that audit and failed 27 of the first 42 tasks of a run —
the end-to-end checks before it had used `--products swc,obj`, so nothing had ever written
an NRRD through the generalised loader.

## Last result — 2026-10-09, 80 neurons (60 strided + 20 named crossers)

160 tasks, 3.9 min, 1.48 s/neuron on 4 workers. **PASS, all nine checks, 0 errors.**
58 deleted spurious, 102 replaced; 20/20 crossers wrote both halves; NRRD non-zero voxels
109 / 3,544 / 72,174 (min/median/max); live tree 4.1 GB -> 949 MB.

`--archive` was also verified as a real undo: restoring from it returned the mirror to its
exact baseline file count.
