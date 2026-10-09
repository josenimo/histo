# josenimo/histo

Processing, segmentation and quantification of multiplex immunofluorescence (mIF) images.
H&E is planned and not supported: `technology` accepts `ome_tif` only.

> [!WARNING]
> **Version 1.1.0.** Runs end to end on real data (mIF, TMA, WSI). The samplesheet and marker
> sheet columns are stable. QC thresholds were calibrated on a single slide, so check your results.

[![Nextflow](https://img.shields.io/badge/version-%E2%89%A525.10.4-green?style=flat&logo=nextflow&logoColor=white&color=%230DC09D&link=https%3A%2F%2Fnextflow.io)](https://www.nextflow.io/)
[![nf-test](https://img.shields.io/badge/unit_tests-nf--test-337ab7.svg)](https://www.nf-test.com)
[![run with singularity](https://img.shields.io/badge/run%20with-singularity-1d355c.svg?labelColor=000000)](https://sylabs.io/docs/)

## What this is

A Nextflow pipeline for imaging data from human tissue, built to run unattended on colleagues'
datasets as well as my own. It combines two existing projects:

| Source                                                | What is taken from it                                                                                   |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| [nf-core/mcmicro](https://github.com/nf-core/mcmicro) | Preprocessing: illumination correction, stitching and registration, background subtraction, TMA dearray |
| [nf-core/sopa](https://github.com/nf-core/sopa)       | Everything from segmentation onward: SpatialData object, tiled segmentation, aggregation, reporting     |

The handoff between the two halves is a single stitched OME-TIFF. Segmentation is tiled, so it is
size independent: images from 5 GB to 100 GB run the same way.

This is a **personal pipeline, not an nf-core pipeline**, and is not affiliated with or endorsed by
nf-core. It follows nf-core conventions for reproducibility and to keep upstream contributions open.

## Steps

Preprocessing (from mcmicro):

1. Illumination correction (BaSiCPy)
2. Stitching and registration (Ashlar)
3. Background subtraction (backsub), optional: `--use_backsub`
4. TMA dearray (UNetCoreograph), optional: `--use_tma_dearray`

Downstream (from sopa):

5. SpatialData Zarr conversion and channel naming from the marker sheet
6. Tiled cell segmentation with Cellpose or StarDist, optionally skipping empty tiles
7. Aggregation of mean channel intensity per cell
8. QC report per sample, and for a TMA a merged object per slide

Input is `ome_tif` mIF. H&E is planned, not supported. `--use_preprocessing false` starts from an
already stitched image. At startup the run stops if the Ashlar or Coreograph channel is not `dna`
in the marker sheet; `--skip_reference_dna_check` overrides.

## Usage

```bash
nextflow run josenimo/histo -r dev \
    -profile singularity,size_small,slurm \
    -params-file params.yml
```

Needs Nextflow >= 25.10.4, a container engine and pre-staged images (no pulls at launch).

| Doc                                              | Contents                                        |
| ------------------------------------------------ | ----------------------------------------------- |
| [docs/usage.md](docs/usage.md)                   | Samplesheet, marker sheet, parameters, defaults |
| [docs/output.md](docs/output.md)                 | What comes out and how to read the QC report    |
| [docs/containers.md](docs/containers.md)         | Image manifest and pre-staging on the cluster   |
| [docs/pipeline-paths.md](docs/pipeline-paths.md) | The routes through the pipeline, as a map       |
| [docs/decisions.md](docs/decisions.md)           | Why it is built this way                        |
| [tests/README.md](tests/README.md)               | Test tiers and how to run them                  |
| [ROADMAP.md](ROADMAP.md)                         | Open work, known limits, verified runs          |
| [CHANGELOG.md](CHANGELOG.md)                     | Release notes                                   |

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
