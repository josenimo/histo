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
- The size profiles (`small`, `medium`, `huge`) for inputs from 5 GB to 100 GB.
- Container pre-staging, since the cluster cannot be relied on to pull images at runtime.

## Meanwhile

For the mechanics of running any Nextflow pipeline — `-profile`, `-resume`, `-c`, configuration and
resource requests — see the [Nextflow documentation](https://www.nextflow.io/docs/latest/) and
[nf-core's running-pipelines docs](https://nf-co.re/docs/usage/getting_started/introduction). Those
are maintained upstream and duplicating them here would only let them drift.

One rule that does apply already: supply parameters via `-params-file` or the CLI, never via `-c`.
Custom config files can set any configuration **except** parameters.
