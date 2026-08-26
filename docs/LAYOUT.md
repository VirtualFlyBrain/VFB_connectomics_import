# Repository layout

Reorganised 2026-08-26. Three concerns, one installable package, entry points instead of
file paths.

```
pyproject.toml                     packaging + console scripts
requirements.txt                   pinned deps (consumed by pyproject)
README.md
docs/                              every .md except README and dashboard/
src/vfb_connectomics_import/
    connectivity/                  neuron-to-neuron edge import
        core.py                    ConnectomicsImport  (was connectomics_import.py)
        cli/{banc,catmaid,flywire,neuprint}.py   (were script_runner_*.py)
        data_owl/ data_tsv/ resources/           (were OWL/ tsv/ resources/)
    curation/                      anat_ TSV generation for the curation interface
        {banc,manc,optic_lobe,flywire}.py        (were *_import.py)
    images/                        neuron images onto the VFB templates
        loader.py                  the job            (was banc_image_loader.py)
        io.py                      served-file contract (was banc_image_io.py)
        transforms.py              baked BANC fields  (was banc_baked.py)
        bake_fields.py             builds those       (was bake_banc_fields.py)
        compare.py                 old-vs-new HTML    (was banc_compare_html.py)
tests/
    test_images.py                 24 tests, no network/navis needed
dashboard/                         unchanged
```

**Split by concern, not by dataset.** The datasets share code *within* a concern — all four
curation modules emit `anat_` TSVs, all four connectivity CLIs share `ConnectomicsImport` —
so `banc/`, `malecns/`, … would have duplicated more than it separated.

## Invoking things

Prefer the console scripts, so a future re-layout does not break job configs:

| | |
|---|---|
| `vfb-banc-images` | `images.loader:main` — the image job |
| `vfb-banc-compare` | `images.compare:main` — old-vs-new HTML |
| `vfb-banc-bake` | `images.bake_fields:main` — rebuild the baked fields |
| `vfb-n2n-banc` | `connectivity.cli.banc:main` |

Without installing, `PYTHONPATH=src python -m vfb_connectomics_import.images.loader` is
equivalent.

`connectivity/cli/{catmaid,flywire,neuprint}.py` have **no `main()`** — they are top-level
run-and-edit scripts (`flywire.py` hardcodes its dataset), so they get no console script.
Run them with `python -m …` , which executes module-level code. Give them a `main()` if you
want entry points; deliberately not done during the re-layout because they are working code.

## Path changes that break existing Jenkins jobs

| old | new |
|---|---|
| `src/VFB_connectomics_import/script_runner_BANC.py` | `-m vfb_connectomics_import.connectivity.cli.banc` |
| `src/VFB_connectomics_import/script_runner_CATMAID.py` | `-m vfb_connectomics_import.connectivity.cli.catmaid` |
| `src/VFB_connectomics_import/script_runner_FlyWire.py` | `-m vfb_connectomics_import.connectivity.cli.flywire` |
| `src/VFB_connectomics_import/script_runner_neuPrint.py` | `-m vfb_connectomics_import.connectivity.cli.neuprint` |

The package directory also changed case, `VFB_` → `vfb_`. That is invisible on macOS
(case-insensitive filesystem) but **not** on the Linux agents, so any job using the old
casing will fail there even if it appears fine locally.
