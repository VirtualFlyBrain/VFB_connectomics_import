# maleCNS: served now vs the rebuilt pipeline

The harness behind the comparison published at
<https://claude.ai/artifact/Ffn6df6ez97NnWeAC2obAp> (measured 2026-10-02). It exists so the
evidence for the rebuild can be regenerated rather than remembered — an earlier run of the
same comparison was lost with its scratch directory.

These are **verification scripts, not library code**. `newpipe.py` predates the
generalisation of `loader.py` and drives `connectomes`/`sources`/`chain` directly; the
loader now does the same thing properly, so prefer

    vfb-em-images --connectome malecns --region both --roots ... --write-root /tmp/out

for anything that matters. What is still worth keeping here is the *comparison*: fetching
what VFB serves today and measuring it against what the pipeline would write.

| script | what it does |
|---|---|
| `kb.py` | minimal KB cypher client |
| `panel.py` | resolves the 8-neuron panel to accessions and per-template folders |
| `newpipe.py` | the pre-generalisation prototype of the LOD rule (kept for provenance) |
| `prep_display.py` | decimates old and new meshes to a display budget |
| `containment.py` | share of each mesh's surface area inside the template neuropil |
| `render.py` | builds the local comparison page |
| `sample_split.py` | how many neurons have material in each region (the ~161,000 figure) |

## What it found

- Every maleCNS neuron is written whole into **both** templates; the copy in the wrong one
  scores **0.0%** inside that template's neuropil. 86.7% of neurons are brain-only and
  10.0% VNC-only, so ~161,000 of the 333,402 image folders hold a file that should not
  exist.
- The registration was never wrong. On channels at the same rung, new matches served to a
  median of **16 nm** (brain) and **53 nm** (VNC) — far below one display voxel. The whole
  defect is the missing cut.
- 2,151 MB → 362 MB raw across the panel, with no change to the four channels that were
  already correct (all within ±1 point of their previous containment).

Needs `KB_USER`/`KB_PASSWORD`, `IMAGE_FIELD_DIR`, and the venv at
`~/Documents/venvs/VFB_connectomics_import` (see `docs/TRANSFORMS.md`).
