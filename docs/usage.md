# josenimo/histo: Usage

> [!WARNING]
> **The pipeline is not runnable yet.** It is at `0.1.0dev`. The downstream half is an unmodified
> import of nf-core/sopa and the preprocessing half does not exist. This page will be written when the
> input format is settled, which is Phase 2 of [ROADMAP.md](../ROADMAP.md).

This page was deliberately emptied rather than rebranded. The previous version documented
nf-core/sopa's samplesheet format for spatial transcriptomics platforms (Xenium, MERSCOPE, CosMx,
Visium HD), none of which is in scope here. Documenting an input format that is about to change would
be worse than documenting nothing. The original is recoverable from commit `33e0863`.

## What will go here

- The samplesheet format, once the multi-cycle mIF input shape is decided.
- The parameters, which will be supplied with `-params-file params.yml` and validated against
  `nextflow_schema.json`. Parameter documentation is generated from that schema rather than
  maintained here by hand.
- Container pre-staging, which now lives in [containers.md](containers.md).

## Choosing `patch_width_pixel`

This one parameter decides whether segmentation parallelises at all, and it is deliberately **not**
computed for you. It affects results at patch boundaries as well as runtime, so an automatically
chosen value would mean the same slide segmenting slightly differently on different hardware.

Pick it so the image yields roughly **16 to 200 patches**:

```
patch_width_pixel = sqrt(width * height / target_patches)
```

| Stitched image | 2000 | 5000 | 8000 | 10000 |
| -------------- | ---- | ---- | ---- | ----- |
| 3k × 3k        | 4    | 1    | 1    | 1     |
| 25k × 25k      | 169  | 25   | 16   | 9     |
| 50k × 50k      | 625  | 100  | 49   | 25    |
| 115k × 115k    | 3364 | 529  | 225  | 144   |

Both ends of that table are failure modes. **One patch means no parallelism**, which discards the
main reason this pipeline uses sopa — a 3138 × 2511 image at the default 5000 produces exactly one
segmentation task. **Thousands of patches** means thousands of container starts and scheduler
submissions, which on a busy queue costs more than the segmentation does.

Memory is not the deciding factor. A 5000-pixel patch of one channel is about 50 MB, so patch size is
a task-count decision, not a memory one. Aim for a few times your cluster's concurrency
(`executor.queueSize`, currently 50) and no more.

To get the dimensions before you run:

```bash
scratch/inspect-ome.py stitched.ome.tif          # on an existing stitched image
showinf -nopix -omexml-only raw_cycle01.ome.tiff # on a raw cycle, then multiply by the tile grid
```

`patch_overlap_pixel` is a different question: set it to roughly twice the diameter of a cell, so
that cells straddling a boundary appear whole in at least one patch.

## Meanwhile

For the mechanics of running any Nextflow pipeline — `-profile`, `-resume`, `-c`, configuration and
resource requests — see the [Nextflow documentation](https://www.nextflow.io/docs/latest/) and
[nf-core's running-pipelines docs](https://nf-co.re/docs/usage/getting_started/introduction). Those
are maintained upstream and duplicating them here would only let them drift.

One rule that does apply already: supply parameters via `-params-file` or the CLI, never via `-c`.
Custom config files can set any configuration **except** parameters.
