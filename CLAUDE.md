# Project context for agentic assistants

Read this before proposing changes. It layers on top of the vendored nf-core
[AGENTS.md](AGENTS.md) and wins where they conflict. Design reasoning is in
[docs/decisions.md](docs/decisions.md), open work in [ROADMAP.md](ROADMAP.md).

## 1. Who I am and what I need

I am a bioimage analyst working with multiplex immunofluorescence (mIF) images of human
tissue. This pipeline processes raw images, segments cells, quantifies features and runs QC.
It must run unattended on colleagues' datasets.

Priorities, in order: **transparency, robustness, easy troubleshooting**. Prefer boring,
explicit, inspectable solutions over clever ones.

This is a private pipeline, not nf-core, and must not be branded as one. Follow nf-core
guidelines anyway, so modules or the pipeline can go upstream later.

## 2. Architecture (settled)

- Preprocessing from nf-core/mcmicro: BaSiCPy and Ashlar (required), then Coreograph dearray
  and backsub (optional, default `false`).
- Everything downstream from nf-core/sopa: SpatialData on Zarr, tiled segmentation,
  aggregation. Tiling is what makes segmentation size-independent; it is the core reason for
  the design.
- A new pipeline from the nf-core template, not a fork of sopa. The handoff between the two
  halves is the stitched OME-TIFF; keep it clean.

## 3. Repository conventions

- Branches: `main` released, `dev` integration, feature branch → PR into `dev`. Keep `TEMPLATE`.
- Keep `CITATIONS.md` (mcmicro, sopa, every tool), `CHANGELOG.md` and `conf/slurm.config` current.
- Never hand-edit `nextflow_schema.json`; use `nf-core pipelines schema build`.
- Optional steps are schema booleans with `default: false`.
- After rewiring the graph, run
  `nf-metro render docs/pipeline_paths.mmd -o docs/images/pipeline_paths.svg` and have a human
  look at it. See [docs/pipeline-paths.md](docs/pipeline-paths.md).

## 4. Modules

- If it exists in nf-core/modules, install it. Do not write it.
- Modules copied from sopa keep their licence header, `meta.yml` and a comment with the source
  commit.
- Newer tool versions: edit the installed module, then `nf-core modules patch <name>`. Vendor
  to `modules/local/` only when the change is more than a version bump.
- Bump the `versions.yml` capture with the container. A bump needs an existing image; prefer a
  bioconda recipe bump upstream over a private image.
- `modules.json` is the lockfile; always commit it. Run `nf-core modules update` with
  `--preview`, never blindly.

## 5. Containers

The laptop is macOS arm64; the cluster is Linux amd64, SLURM, Apptainer, with unreliable
internet. Hence:

1. No runtime container pull or launch-time network dependency, including Wave. All images
   are pre-staged. See [docs/containers.md](docs/containers.md).
2. No real container runs on the Mac. The Mac is for writing code and running `-stub`.
3. `NXF_SINGULARITY_CACHEDIR` is a shared path, set in config, not per run.
4. Every image URI is in the manifest (`tools/container_manifest.py`).

Wave is a development tool only: conda-to-container, multi-arch builds, `freeze` or `mirror`
into a registry I control. Committed config references static URIs.

## 6. Testing

Tiers, cheapest first: prek hooks, `nf-core pipelines lint`, pytest, validation and stub
nf-tests (CI), then two exemplar runs on the cluster before each release. Details in
[tests/README.md](tests/README.md).

- `-stub` checks channel topology only, not tool behaviour or resources.
- A module that creates a file (including `versions.yml`) needs a stub. prek enforces this.
- Update a stub in the same commit as the outputs it mirrors.
- sopa modules mutate the Zarr in place, through symlinks into the previous task's work
  directory. Suspect this first when `-resume` or parallel runs misbehave.

Run the checks before calling a task done. Following guidelines by eye is not enough.

## 7. On the HPC cluster

- Raw imaging data is read-only. Never write, move or delete it.
- Never run `sbatch` or `srun`. Propose the command; I submit.
- Never touch the shared `NXF_SINGULARITY_CACHEDIR`.
- Only clean up `work/` directories in your own scratch.
- Mind the shared quota. No large outputs unprompted.
- No `rm -rf` on a variable path without showing me the resolved path first.

## 8. How to work with me

- You commit; I push and open PRs. Never `git push` or `gh pr create`.
- Ask before large refactors. I need to understand every change.
- Small, single-concern commits.
- **Be brief.** Commit titles under ~60 characters, bodies a few lines or none. PR titles and
  bodies short. Code comments are one line of "why". Do not keep superseded reasoning in docs;
  git history has it.
- Default to the simpler option. Flag uncertainty rather than guessing APIs or flags.
- Nextflow is not my native domain; briefly explain Groovy or DSL2 subtleties when they matter.
