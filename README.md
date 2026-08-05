# josenimo/histo

Processing, segmentation and quantification of H&E and multiplex immunofluorescence (mIF) images.

> [!WARNING]
> **Under construction, not yet usable.** This pipeline is at version `0.1.0dev` and is being
> assembled. The downstream half is currently an unmodified import of [nf-core/sopa](https://github.com/nf-core/sopa),
> and the preprocessing half does not exist yet. Do not use it for analysis. See
> [ROADMAP.md](ROADMAP.md) for the plan and the [open issues](https://github.com/josenimo/histo/issues)
> for progress.

[![Nextflow](https://img.shields.io/badge/version-%E2%89%A525.10.4-green?style=flat&logo=nextflow&logoColor=white&color=%230DC09D&link=https%3A%2F%2Fnextflow.io)](https://www.nextflow.io/)
[![nf-test](https://img.shields.io/badge/unit_tests-nf--test-337ab7.svg)](https://www.nf-test.com)
[![run with singularity](https://img.shields.io/badge/run%20with-singularity-1d355c.svg?labelColor=000000)](https://sylabs.io/docs/)

## What this is

A Nextflow pipeline for imaging data from human tissue, built to run unattended on datasets from
colleagues as well as my own. It combines two existing projects:

| Source | What is taken from it |
| --- | --- |
| [nf-core/mcmicro](https://github.com/nf-core/mcmicro) | Preprocessing: illumination correction, stitching and registration, background subtraction, TMA dearray |
| [nf-core/sopa](https://github.com/nf-core/sopa) | Everything from segmentation onward: SpatialData object, tiled segmentation, aggregation, reporting |

The handoff between the two halves is a single stitched OME-TIFF.

sopa was chosen for the downstream half because its segmentation is **size independent**: it tiles
the image, segments each tile, and parallelises across an HPC cluster, backing everything with a
Zarr-based [SpatialData](https://github.com/scverse/spatialdata) object. Input images here run from
5 GB to 100 GB, so that property is the single most important capability in the design.

This is a **personal pipeline. It is not an nf-core pipeline** and is not affiliated with or
endorsed by the nf-core community. It follows nf-core conventions because they genuinely help with
reproducibility, and to keep open the option of contributing modules upstream later.

## Planned steps

Preprocessing, from nf-core/mcmicro:

1. Illumination correction (BaSiCPy) — required
2. Stitching and registration (Ashlar) — required
3. Background subtraction — optional, `--use_backsub`
4. TMA dearray (UNetCoreograph) — optional, `--use_tma_dearray`

Downstream, from nf-core/sopa:

5. Conversion to a SpatialData Zarr object
6. Optional tissue segmentation, to skip empty tiles
7. Tiled cell segmentation with Cellpose, parallelised per tile
8. Aggregation of channel intensities per cell
9. QC report and Xenium Explorer export

## Usage

Not yet. When the pipeline is runnable this section will describe the samplesheet format and the
parameters. Parameters will be supplied with `-params-file params.yml`, validated against
`nextflow_schema.json`.

## Credits

Written by Jose Nimo at the Max Delbrück Center for Molecular Medicine, Berlin.

This pipeline is derived from two MIT licensed projects and would not exist without them:

- **nf-core/sopa**, written by [Quentin Blampey](https://github.com/quentinblampey) and
  contributors. The downstream half of this pipeline is derived from it, and many modules are
  vendored from it with their original licence headers and source commits recorded.
- **nf-core/mcmicro**, from the Laboratory of Systems Pharmacology and the nf-core community.

See [`CITATIONS.md`](CITATIONS.md) for the full list of tools and their references.

## Citations

**This pipeline has no DOI and should not be cited in place of the tools it wraps.** If you use it,
cite the underlying tools. The two most important:

> **Sopa: a technology-invariant pipeline for analyses of image-based spatial omics.**
>
> Quentin Blampey, Kevin Mulder, Margaux Gardet, Stergios Christodoulidis, Charles-Antoine Dutertre,
> Fabrice André, Florent Ginhoux & Paul-Henry Cournède.
>
> _Nat Commun._ 2024 June 11. doi: [10.1038/s41467-024-48981-z](https://doi.org/10.1038/s41467-024-48981-z)

> **The nf-core framework for community-curated bioinformatics pipelines.**
>
> Philip Ewels, Alexander Peltzer, Sven Fillinger, Harshil Patel, Johannes Alneberg, Andreas Wilm,
> Maxime Ulysse Garcia, Paolo Di Tommaso & Sven Nahnsen.
>
> _Nat Biotechnol._ 2020 Feb 13. doi: [10.1038/s41587-020-0439-x](https://dx.doi.org/10.1038/s41587-020-0439-x)

## Licence

MIT. See [`LICENSE`](LICENSE).
