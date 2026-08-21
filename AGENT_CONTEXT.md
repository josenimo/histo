# Project context for agentic assistants

This document is the authoritative context for work on this pipeline. Read it fully before
proposing changes. Where it conflicts with generic nf-core defaults, **this document wins**.

---

## 1. Who I am and what I need

I am a **bioimage analyst** working with **H&E and multiplex immunofluorescence (mIF) imaging
data**, mainly of human tissue.

I need a **Nextflow pipeline** that will:

1. Process raw imaging data
2. Segment cells
3. Quantify features
4. Run QC at the end — for my own inspection, and to validate runs on colleagues' datasets

The pipeline must run **unattended on datasets from colleagues**, not just my own. Therefore:

**My priorities, in order:**

1. **Transparency** — it must be clear what is being done, and why. This is the top value.
2. **Robustness** — consistent, reproducible results across datasets.
3. **Easy to troubleshoot** — when it breaks, the failure should be legible.

Speed and elegance are secondary to the three above. Prefer boring, explicit, inspectable
solutions over clever ones.

**Scope note:** this is a **private, personal pipeline**. It is _not_ an nf-core pipeline and
must not be branded as one. However, I want to follow every nf-core community guideline, because
(a) the conventions genuinely help with the priorities above, and (b) I may eventually contribute
modules or a pipeline upstream. Do not foreclose that option.

---

## 2. Architectural decision (settled — do not relitigate)

The pipeline combines two existing projects:

| Source              | What I take from it                                                                                                  |
| ------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **nf-core/mcmicro** | Preprocessing: illumination correction, stitching & registration, background subtraction, TMA dearray (`coreograph`) |
| **nf-core/sopa**    | Everything from segmentation onward: SpatialData object, tiled segmentation, aggregation, QC                         |

**Step requirements:**

- **Required:** illumination correction, stitching/registration
- **Optional, opt-in (default `false`):** background subtraction, TMA dearray

**Why sopa downstream:** sopa implements a **SpatialData object backed by Zarr**, which gives
cloud-compatible lazy reading. Critically, its **segmentation is size-independent** — it tiles the
image, segments per tile, and parallelises across an HPC cluster. This is the single most important
capability in the whole design.

**Why mcmicro upstream:** its preprocessing modules are what I need, and they now exist as an
nf-core pipeline. (My experience ~2 years ago was that very large images broke at mcmicro's
segmentation step — this may be fixed, but sopa's tiling approach is the reason I want sopa
downstream regardless.)

**DECISION: build a new custom pipeline. Do NOT fork nf-core/sopa.**

Forking means owning a permanent merge conflict against two actively developed repositories, which
directly undermines transparency and troubleshootability. Instead: a new pipeline scaffolded with
`nf-core pipelines create` (answering **"no"** to "is this an nf-core pipeline?"), which strips
nf-core branding and org CI while keeping the conventional skeleton, linting, and the `TEMPLATE`
branch so `nf-core pipelines sync` continues to work.

**The handoff boundary between the two halves is the stitched OME-TIFF.** Keep it clean.

---

## 3. Prior state — important history

Before this plan, I had a **scrappy, hand-modified copy of nf-core/sopa** with mcmicro modules
grafted in, built with agentic AI assistance and **without version control**. I do not fully
understand my own changes relative to upstream sopa.

**The archaeology step:** `git init` that tree, commit as-is, add upstream sopa as a remote at the
release it was branched from, and diff. That diff is the inventory of what I changed.

**Do not migrate the scrappy tree wholesale.** Port from it deliberately, reapplying changes as
small, single-concern commits — one per module, one for config, one for schema — so the history
explains itself.

---

## 4. Repository conventions

- Branches: `main` = released, `dev` = integration, feature branches → PR into `dev`.
  Even working solo, use PRs into `dev` for a reviewable history.
- Pipeline name: **lowercase, no hyphens or underscores** (Nextflow uses the repo name as the
  pipeline name).
- Keep the `TEMPLATE` orphan branch.
- Required housekeeping, maintained as we go, not retrofitted:
  - `CITATIONS.md` — must credit **mcmicro, sopa, and every underlying tool**
  - `CHANGELOG.md` — semantic versioning
  - `LICENSE` — MIT
  - `conf/` institutional profile for my SLURM setup
- **Never hand-edit `nextflow_schema.json`.** Use `nf-core pipelines schema build`.
- **Re-render the metro map whenever the graph is rewired**, and look at it. Any change to
  `workflows/histo.nf`, to a subworkflow's wiring, or to which process publishes what, ends with
  `nf-metro render docs/pipeline_paths.mmd -o docs/images/pipeline_paths.svg` and a human reading
  the result. It is the one check that catches a rewiring that runs green and is still wrong:
  tests assert that processes ran, the map shows what feeds what. See
  [docs/pipeline-paths.md](docs/pipeline-paths.md).
- Optional steps are booleans in the schema with `default: false`, so they self-document via `--help`.
- Tag `1.0.0` off `main` once the two required preprocessing steps plus segmentation run
  end-to-end, even if optional steps are unfinished. A tag is what makes `-r 1.0.0` reproducible
  for colleagues.

**Structure:** two subworkflows in `subworkflows/local/`, roughly

- `PREPROCESS_IMAGES` — illumination correction → stitching/registration → optional backsub → optional dearray
- `SPATIAL_ANALYSIS` — SpatialData conversion → tiled segmentation → aggregation → QC

---

## 5. Modules

**Sourcing rules:**

- If it exists in `nf-core/modules`, **install it, don't write it**
  (`nf-core modules install <name>`). Installed modules bring pinned containers, `meta.yml`, and
  nf-test files, and can be updated with `nf-core modules update`.
- If it only exists in nf-core/sopa's `modules/local/`, copy it into my `modules/local/` —
  **preserving the license header, the `meta.yml`, and a comment recording the source commit.**
  Both projects are MIT; attribution is both a license requirement and part of the transparency goal.
- Where a vendored module is genuinely reusable, the right move is to contribute it upstream to
  `nf-core/modules` so it can be installed rather than vendored.

**Version bumps (I want newer tool versions than nf-core ships):**

Example: `backsub` is at v0.4.x in nf-core/mcmicro but v0.5.x upstream. I want the newer versions,
**but only after I have tested them, and only manually.**

- Preferred mechanism: **`nf-core modules patch <name>`**. Edit the installed module (container/conda
  directive + version capture), then run `patch` — it writes a `.diff` recorded in `modules.json`,
  so the change survives `nf-core modules update` and produces a visible conflict rather than a
  silent clobber if upstream touches the same lines.
- Vendor to `modules/local/` only when changes exceed a version bump (different CLI flags, changed
  outputs). This forfeits `nf-core modules update` for that module.
- **`modules.json` is the lockfile** — it pins an exact `nf-core/modules` commit SHA per module.
  Always commit it. It is what makes module versions reproducible for colleagues.
- Updates are never automatic; always use `--preview` to inspect the diff first.
- **A version bump only works if a container image for that version exists.** Check
  quay.io/biocontainers, then the tool developers' own registry, then fall back to building.
- **The durable fix is upstream:** nf-core modules lag because bioconda recipes lag. A version-bump
  PR to `bioconda-recipes` is usually a few lines, triggers an automatic BioContainers build, and
  fixes the problem for everyone. Prefer this over maintaining a private image.
- **Always update the `versions.yml` capture block** when bumping. If the version is hardcoded there
  and not bumped, provenance in the MultiQC report is silently wrong.

---

## 6. Containers — constraints and rules

**Hard environment constraints:**

- My laptop is **macOS on Apple Silicon (M3) = `linux/arm64`**.
- The cluster is **Linux, SLURM, `linux/amd64`**, using Apptainer/Singularity.
- Essentially all BioContainers are **amd64-only**. Emulation on my Mac is slow and, for
  numerically heavy imaging code, sometimes wrong or broken.
- **The cluster has intermittently poor internet.** It frequently fails to pull containers on demand.

**Therefore, non-negotiable rules:**

1. **Never introduce a runtime container pull or any launch-time network dependency.**
   All images are pre-staged. This includes not adding a Wave dependency resolved at launch.
2. **Do not attempt local container execution for real work.** The target is amd64 on SLURM.
   My Mac is for writing code and running `-stub`. Do not spend effort on emulation workarounds.
3. `NXF_SINGULARITY_CACHEDIR` points at a **shared filesystem path, not `$HOME`**, set in shell
   config and institutional Nextflow config — not passed per-run.
4. Maintain a **container manifest in version control**: a script or list of every image URI in the
   pipeline. This sits alongside `modules.json` as a reviewable record.

**Pre-staging workflow:** on a well-connected machine, run
`nf-core pipelines download <pipeline> -r <tag> --container-system singularity` to resolve and fetch
every SIF, then rsync into the shared cache.

**Building images** (only when no suitable image exists): Dockerfile from a micromamba/conda-forge
base, exact pinned versions, built with `docker buildx build --platform linux/amd64` and pushed to
ghcr.io or quay.io. Building SIF directly needs Linux + root/fakeroot, so generally not on the Mac.

**On nf-core "approval":** containers are not reviewed as containers. nf-core requires images from
bioconda/BioContainers (or mulled multi-package images); custom Dockerfiles in modules are
effectively disallowed. So the review path is a **bioconda recipe review**. Not required for this
private pipeline, but following it preserves the upstream contribution option.

**Wave / Seqera Containers — how I want it used:**

Wave is a **development-time tool only**. Acceptable uses:

- Conda-to-container mode, to get an image for a tool version with no BioContainer yet
  (fastest route around bioconda lag)
- Multi-arch builds, to get an **arm64** image for local iteration from the same spec as the amd64 one
- `wave.freeze = true` with `wave.build.repository`, to build once and push a permanent immutable
  image to a registry I control
- `wave.mirror = true`, to copy containers (including nf-core ones with hardcoded `container`
  directives) into an institutional registry — potentially high value given the network situation
- Wave can emit SIF directly, removing the docker→SIF conversion step

**Unacceptable:** Wave resolving containers at launch time. Freeze or mirror, pre-pull the SIFs, and
let the committed config reference plain static registry URIs. Wave in the dev loop; static images in
production.

Note Wave-built images cannot be used by nf-core modules — Wave applies to `modules/local/` only.
If depending on Seqera Containers' hosted images, mirror anything critical into a registry I control
rather than relying on a free tier for a pipeline colleagues will run for years.

---

## 7. Testing

> **Amended 2026-08-06.** This section originally called `-stub` the primary feedback loop and
> required stub blocks for every `modules/local/` module. That was written before we understood how
> sopa's modules behave. Superseded reasoning is kept below the line so the change is auditable.

**Layered, cheapest first:**

1. `singularity exec image.sif <tool> --version` — proves the image runs and is the expected version.
   Most container problems surface here, in seconds.
2. `nf-core modules test <name>` — nf-test, using the module's own snapshots.
3. **Pipeline `-stub` run** — a channel-topology check, not a correctness check. See below.
4. **`-profile test` with `technology = toy_dataset`** — the real fast loop. Synthetic SpatialData is
   generated in-process, so it needs no input data and runs in minutes with real code and real
   containers. This is what sopa themselves use, and it is why sopa ships no stub blocks.
5. Tiny real data on the cluster.
6. `test_full` before tagging.

### Why sopa has no stubs, and what that means here

**Most sopa modules mutate the SpatialData Zarr in place.** Five of eleven declare their input zarr
as their output and create no new file: `aggregate`, `fluo_annotation`, `tissue_segmentation`,
`resolve_cellpose`, `resolve_stardist`. Nextflow has already staged the input into the work directory,
so the output declaration resolves whether or not the stub does anything. A stub block for those
modules is ceremony.

This is not a traditional file-in, file-out pipeline, and the nf-core stub convention assumes one.

**Consequences to keep in mind, beyond testing:** Nextflow stages inputs as symlinks, so a process
writing into `sdata_path` writes into the _previous_ task's work directory. Tasks share mutable state
and the DAG is not a pure dataflow graph. Expect this to matter for `-resume` correctness and for
parallel safety; check `stageInMode` when something behaves oddly.

### The revised rule

**Write a stub block only where a module declares an output file it actually creates.** For a module
whose only output is its mutated input, an empty stub adds nothing and creates the illusion of
coverage.

**In practice this still means nearly every module**, and the reason is worth following: `versions.yml`
counts as a created file. Provenance matters more than stub minimalism, so every module should emit
versions, and a module that emits versions needs a stub that writes them. The difference from the
original blanket rule is not the count but the principle: a stub exists because the module creates
something, not because it is a module. For pass-through modules that stub is three lines, the versions
heredoc and nothing else, which is honest about how little it is checking.

`-stub` is worth keeping for what it genuinely catches: cardinality mismatches, wrong tuple shapes,
missing `meta` keys, optional-step conditionals that silently empty a channel, output filenames not
matching declarations, and param/schema validation. That is exactly the risk profile of the
preprocessing half — multi-cycle fan-out, dfp/ffp positional ordering, TMA core fan-out — so stubs
matter most for modules added from mcmicro, and least for the inherited sopa ones.

**`-stub` proves nothing about tool behaviour, correctness, or resource requirements.** Treat it as a
compile check for the DAG.

**Stub blocks still rot.** Where a stub exists and the module's outputs change, update it in the same
commit; a stale stub passing while the real run fails is worse than no stub.

### Local execution on Apple Silicon

sopa ships arm64 conda-locks for 7 of 11 modules. The four without are
`patch_segmentation_cellpose`, `patch_segmentation_stardist`, `resolve_cellpose` and
`resolve_stardist` — the segmentation steps, presumably because of PyTorch and TensorFlow. So a
native arm64 local run is partially possible but excludes the expensive and interesting steps. Not a
substitute for cluster testing; possibly useful for iterating on conversion and aggregation.

---

<details>
<summary>Superseded: the original section 7 reasoning</summary>

> **`-stub` is the primary fast feedback loop.** ... Because stub commands are trivial shell, `-stub`
> runs are viable on my Mac even when the amd64 containers underneath are not. This is my one
> meaningful local test loop. ... Write stubs for all `modules/local/` modules.

Why this was wrong: it assumed every module produces new output files, so a stub would meaningfully
fake something. It also assumed no faster loop existed, when sopa's `toy_dataset` profile runs the
real code on synthetic data in minutes. The Mac constraint is real, but it makes `-stub` the only
_local_ loop, not the primary one overall.

</details>

**Test data:** a `test` profile with a deliberately tiny input (cropped 2-channel tile, 4-core TMA)
and a `test_full` profile for a real dataset. Test data lives in my own small repo
(`nf-core/test-datasets` requires org membership).

---

## 8. Machine-checkable rules over prose

Written guidance drifts; failing checks do not. Much of nf-core convention is already
machine-checkable, so **compliance should come primarily from tooling**:

- `nf-core pipelines lint`
- `nf-test`
- `pre-commit` (prettier, editorconfig)
- a `-stub` run in CI

**Run these before claiming a task is done.** Do not report work as complete on the basis of having
followed the guidelines by eye.

---

## 9. Agent operating constraints on the HPC cluster

I am deliberately cautious about agentic access to the cluster. Filesystem permissions and
containment are the real boundary; agent-level allow/deny config is a seatbelt, not a wall.

**Rules for any agent working on the cluster:**

- **Raw imaging data is read-only.** Never write to, move, or delete it. Treat any dataset from a
  colleague as irreplaceable.
- **Never run `sbatch` or `srun`.** I submit real jobs manually. Propose the command; do not execute it.
- **Never `git push`.** Commit freely; I push.
- **Never touch the shared `NXF_SINGULARITY_CACHEDIR`.** Colleagues depend on it. I pre-stage images.
- **Never run cleanup or deletion commands against Nextflow `work/` directories** that are not the
  agent's own dedicated scratch. Work in an assigned scratch directory only.
- Be mindful of **shared filesystem quota** — do not generate large volumes of output unprompted.
- No `rm -rf` on any path built from a variable without showing me the resolved path first.

Expected containment on my side: read-only bind mounts (`--bind data:/data:ro` with `--containall
--no-home`) or a `chmod a-w` snapshot, a dedicated project + scratch directory, off-cluster backups
of raw data, and a git remote off-cluster.

---

## 10. Open items to verify before relying on them

My planning was done without web access, against knowledge with a **May 2026 cutoff**. Verify
against current documentation before building on any of these:

- Exact `nf-core` CLI subcommands and flags — the command surface was reorganised recently
- Current nf-core/sopa and nf-core/mcmicro releases, and their exact module names
  (reasonably confident on `basicpy` and `ashlar`; less so on `backsub` and `coreograph`)
- Whether nf-core/mcmicro's segmentation still breaks on very large images (my experience is ~2 years old)
- Wave / Seqera Containers config keys, capabilities, free-tier limits, and image retention policy —
  this service has been iterating fast and is the most likely to have moved
- Whether backsub or other mcmicro tools now ship multi-arch images
- ~~Whether the current Nextflow version stages containers during `-stub` runs~~ **Answered
  2026-08-06: no.** Nextflow 26.04.6 ran `-profile test -stub` as `executor > local (9)` with no
  container staging, on macOS arm64, against amd64-only images. `-stub` is therefore a genuine local
  loop, provided stub blocks do not invoke the tool. Ours write `versions: stub` rather than calling
  `sopa --version` for exactly this reason.
- Whether my institution already runs a container registry (Harbor, GitLab, Artifactory) to mirror into
- The contents of the nf-core community `AGENTS.md`
  (`https://github.com/nf-core/agents/blob/main/resources/pipeline/AGENTS.md`) — this should be
  **vendored into the repo verbatim**, not linked, with its source URL, commit SHA, and retrieval
  date recorded so it can be diffed against upstream later. This project-specific document layers
  on top of it and takes precedence where they conflict.

---

## 11. How to work with me

- **Ask before large refactors.** I need to understand every change; I have already been burned by
  accepting changes I did not understand.
- **Small, single-concern commits with clear messages.** The git history is a primary deliverable,
  not a byproduct.
- Explain _why_, not just _what_. If there is a simpler and a cleverer option, default to simpler.
- **Flag uncertainty explicitly** rather than guessing at API details, module names, or flags.
- Nextflow/nf-core is not my native domain — I am a bioimage analyst. Do not assume familiarity with
  Groovy idioms or DSL2 subtleties; explain them briefly when they matter.
