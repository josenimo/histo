# josenimo/histo: Output

## Introduction

This document describes the output produced by the pipeline.

The directories listed below will be created in the results directory after the pipeline has finished. All paths are relative to the top-level results directory.

## Pipeline overview

The pipeline is built using [Nextflow](https://www.nextflow.io/) and outputs the following information:

- [Preprocessing](#preprocessing) - Illumination profiles, the stitched image, and the optional background-subtracted and dearrayed images.
- [SpatialData directory](#spatialdata-directory) - Full [SpatialData](https://spatialdata.scverse.org/en/stable/) object with the segmented and aggregated data.
- [QC report](#qc-report) - Per-sample HTML summary of segmentation and aggregation
- [Pipeline information](#pipeline-information) - Report metrics generated during the workflow execution

### Preprocessing

<details markdown="1">
<summary>Output files</summary>

- `preprocessing/illumination/`
  - `{sample}_cycle{n}-dfp.ome.tif` and `-ffp.ome.tif`, the dark-field and flat-field profiles
    BaSiCPy fitted for each cycle. Absent for a cycle whose profiles were supplied in the
    samplesheet, since nothing was computed.
- `preprocessing/registration/`
  - `{sample}.ome.tif`, the stitched and registered mosaic from Ashlar. **This is the handoff
    boundary between the two halves of the pipeline**, and the file to inspect first when
    segmentation looks wrong.
- `preprocessing/background_subtraction/`
  - `{sample}_backsub.ome.tif` and `{sample}_backsub.csv`. Only when `use_backsub` is true. The
    CSV is backsub's own marker sheet rather than a copy of the input: rows whose `remove` column
    was set are gone and `channel_number` is renumbered over what survives, so this is the sheet
    that describes the image everything downstream reads.
- `preprocessing/dearray/`
  - `{slide}_core001.ome.tif` and one per core, plus `masks/{slide}_core001_mask.tif`,
    `{slide}_coremask.tif`, `{slide}_tma_map.tif` and `{slide}_centroids.txt`. Only when
    `use_tma_dearray` is true. The TMA map and centroids are what to check when a core is missing
    or two cores were merged into one.

</details>

The `_backsub` suffix appears only on backsub's own two files. Core identity comes from the
slide name rather than from the filename it was cut out of, so a slide processed with and without
background subtraction produces cores with matching names.

### SpatialData directory

<details markdown="1">
<summary>Output files</summary>

- `{sample}.zarr/`
  - Spatial elements: `images/`, `shapes/`, `tables/`, `points/`, ...
- `{sample}.zarr/.sopa_cache/`
  - What segmentation left behind: the patch definitions, and one parquet of cell boundaries
    per patch. Reproducible from the store, and about 4% of its size.

</details>

The `{sample}.zarr` directory contains a [SpatialData](https://spatialdata.scverse.org/en/stable/) object, where the `sample` name is either (i) specified by the samplesheet, or (ii) based on the name of the corresponding input directory.

Each cell table's `obs` says where its cells came from, so tables can be concatenated safely:
`slide` is the sample name from the samplesheet, and on a dearrayed TMA `core_id` is the core
(e.g. `TMA01_core001`). Runs without dearraying have no `core_id` column.

Refer to the [SpatialData docs](https://spatialdata.scverse.org/en/stable/) for usage details, or to the [documentation of `sopa` as a Python package](https://prism-oncology.github.io/sopa/). If you are not familiar with `SpatialData`, you can also use directly the extracted `AnnData` object (see below).

`PUBLISH_SPATIALDATA` is what copies the store here, and it exists only for that. Aggregation
and fluorescence annotation both write into the store, and which of them runs last depends on
`use_fluorescence_annotation`, so publishing from either would publish a store the other then
modifies.

### QC report

<details markdown="1">
<summary>Output files</summary>

- `qc/{sample}_qc.json`
  - Every QC metric as machine-readable JSON. **This is the file an unattended run should
    read.** Per-channel intensity statistics measured on every pixel of the full-resolution
    image, cell-area distribution and the count below a degenerate-cell threshold, channel-name
    agreement between the image, the table and the marker sheet, cells per segmentation patch,
    and — when background subtraction ran — the same channel statistics from before
    subtraction, so the two can be compared. That comparison is available on dearrayed slides
    too: `COREOGRAPH` runs before `BACKSUB`, so every core is subtracted on its own and keeps
    an unsubtracted twin of matching shape. It sets no thresholds and returns no
    exit code: the numbers that would justify a threshold need more than one dataset behind them.
- `qc/{sample}_qc_report.html`
  - The same metrics rendered for a person, plus the images. Self-contained: no external
    scripts, fonts or network access, so it can be copied anywhere and opened offline.
    Includes segmentation overlays at full resolution across the density range, a cross-cycle
    nuclear-stain comparison, a Leiden clustering tree over a resolution sweep, the
    cluster-by-marker profile, and representative cells per cluster. Every chart has a table
    view beneath it.
- `qc/{sample}_qc_images/`
  - The PNGs the report embeds, kept as files so they can be used on their own. Absent when
    `--use_qc_images false`.
- `qc/{slide}_slide_report.html`
  - **Dearrayed slides only.** One page for the whole slide, from the per-core metrics: cells
    per core against the slide total, the integrity checks rolled up so a check passes only
    when every core passes and the ones that failed are named, and mean intensity per channel
    with one column per core. That last table is the comparison a single core's report cannot
    make — its own page shows a channel against its own histogram, which says whether the
    channel has signal, not whether it has the same signal as the rest of the slide. Core
    detail that is only actionable on one core, the crops, the clusters, the per-channel
    histograms and the patch layout, stays in that core's report rather than being repeated.

</details>

The per-core QC report is produced per sample, which on a dearrayed slide means per core. `use_qc: false`
skips it entirely; `use_qc_images: false` keeps the metrics and the charts but drops the
clustering and the image crops, which are the slow part. Tuning for the image step — the Leiden
resolution ladder, the arcsinh cofactor, how many crops — goes through `ext.args` for `QC_IMAGES`
in `conf/modules.config` rather than through pipeline parameters.

> [!NOTE]
> Booleans cannot be switched off from the command line, and the pipeline now stops at startup
> rather than doing the opposite of what was asked. `--use_qc false` used to enable QC: Nextflow
> reads the flag on its own, sets it true, and throws the `false` away before any pipeline code
> runs. Set booleans in a params file (`use_qc: false`), which is where a real boolean survives.
> A bare flag still works to switch one on. This applies to every boolean the pipeline has, not
> only these two.

Upstream nf-core/sopa also produced a `{sample}.explorer/` directory holding a Xenium Explorer
bundle and a standalone `adata.h5ad`. **This pipeline does not export to Xenium Explorer.** The
cell table is still available inside `{sample}.zarr` under `tables/`, and can be pulled out with
`spatialdata.read_zarr(...).tables`.

### Pipeline information

<details markdown="1">
<summary>Output files</summary>

- `pipeline_info/`
  - Reports generated by Nextflow: `execution_report.html`, `execution_timeline.html`, `execution_trace.txt` and `pipeline_dag.dot`/`pipeline_dag.svg`.
  - Reports generated by the pipeline: `pipeline_report.html`, `pipeline_report.txt` and `software_versions.yml`. The `pipeline_report*` files will only be present if the `--email` / `--email_on_fail` parameter's are used when running the pipeline.
  - Reformatted samplesheet files used as input to the pipeline: `samplesheet.valid.csv`.
  - Parameters used by the pipeline run: `params.json`.

</details>

[Nextflow](https://www.nextflow.io/docs/latest/tracing.html) provides excellent functionality for generating various reports relevant to the running and execution of the pipeline. This will allow you to troubleshoot errors with the running of the pipeline, and also provide you with other information such as launch commands, run times and resource usage.
