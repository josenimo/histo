#!/usr/bin/env bash
#
# Create the roadmap as GitHub labels, milestones and issues.
#
# Prerequisites:
#   gh auth login          (needs 'repo' scope)
#   gh auth status         (verify)
#
# Usage:
#   ./create_issues.sh --dry-run     # print what would be created, touch nothing
#   ./create_issues.sh               # create for real
#   ./create_issues.sh --force       # create even if milestones already exist
#
# ALREADY RUN: 2026-08-05. The 57 issues and 10 milestones exist.
# Do not run again without --force; it would duplicate every issue.
#
# Idempotency: labels and milestones are safe to re-run (existing ones are
# skipped). ISSUES ARE NOT. Hence the guard below.
#
# Source of truth is ROADMAP.md. If you change the roadmap, change this too.

set -euo pipefail

REPO="josenimo/imaging_pipeline"
DRY_RUN=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --force)   FORCE=1 ;;
        *) echo "Unknown argument: $arg" >&2
           echo "Usage: $0 [--dry-run] [--force]" >&2
           exit 1 ;;
    esac
done

if [[ $DRY_RUN -eq 0 ]]; then
    gh auth status >/dev/null || { echo "Run 'gh auth login' first."; exit 1; }

    # Guard: milestones existing means this has already been run.
    if [[ $FORCE -eq 0 ]] \
       && gh api "repos/${REPO}/milestones?state=all" --jq '.[].title' 2>/dev/null \
          | grep -qxF "Backlog"; then
        echo "Refusing to run: milestones already exist in ${REPO}." >&2
        echo "This script was run on 2026-08-05 and is not idempotent for issues." >&2
        echo "Re-running would create 57 duplicates." >&2
        echo "If you genuinely want that, pass --force." >&2
        exit 1
    fi

    echo "Creating issues in ${REPO} for real."
    echo "This is not idempotent. Re-running will duplicate every issue."
    read -r -p "Type 'yes' to continue: " confirm
    [[ "$confirm" == "yes" ]] || { echo "Aborted."; exit 1; }
fi

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '  [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

echo "== Labels"
mklabel() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '  [dry-run] label %-22s %s\n' "$1" "$3"
    else
        gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force
    fi
}

mklabel "P0"            "b60205" "Correctness defect, blocks real data"
mklabel "P1"            "d93f0b" "Should fix, not blocking"
mklabel "phase-0"       "ededed" "Freeze and diagnose"
mklabel "phase-1"       "ededed" "Scaffold"
mklabel "phase-2"       "ededed" "Preprocessing half"
mklabel "phase-3"       "ededed" "TMA path"
mklabel "phase-4"       "ededed" "Resource profiles"
mklabel "phase-5"       "ededed" "Containers"
mklabel "phase-6"       "ededed" "Testing"
mklabel "phase-7"       "ededed" "QC report"
mklabel "phase-8"       "ededed" "Release"
mklabel "nf-core"       "0e8a16" "nf-core tooling, modules or conventions"
mklabel "containers"    "1d76db" "Container images and pre-staging"
mklabel "testing"       "5319e7" "nf-test, stub runs, CI"
mklabel "metadata"      "fbca04" "OME-XML, channel names, pixel size"
mklabel "bookmark"      "c5def5" "Route identified, not scheduled"
mklabel "upstream"      "bfd4f2" "Contribute back to sopa, mcmicro or bioconda"
mklabel "decision"      "d4c5f9" "Needs a decision from Jose"
mklabel "diagnosis"     "fef2c0" "Read-only investigation, no code change"

# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

echo "== Milestones"
mkmilestone() {
    local title="$1" desc="$2"
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '  [dry-run] milestone %s\n' "$title"
        return
    fi
    if gh api "repos/${REPO}/milestones?state=all" --jq '.[].title' | grep -qxF "$title"; then
        echo "  exists: $title"
    else
        gh api "repos/${REPO}/milestones" -f title="$title" -f description="$desc" >/dev/null
        echo "  created: $title"
    fi
}

mkmilestone "Phase 0: Freeze and diagnose"   "Commit context, archive main as legacy, diagnose the Coreograph metadata problem."
mkmilestone "Phase 1: Scaffold"              "Clone sopa:dev as scaffold, rebrand, delete out-of-scope features, housekeeping."
mkmilestone "Phase 2: Preprocessing half"    "mcmicro modules, PREPROCESS_IMAGES subworkflow, schema."
mkmilestone "Phase 3: TMA path"              "Coreograph fix at the producer, core IDs, gated incremental merge."
mkmilestone "Phase 4: Resource profiles"     "small/medium/huge size profiles, resourceLimits, institutional config."
mkmilestone "Phase 5: Containers"            "Restore upstream URIs, container manifest, pre-staging."
mkmilestone "Phase 6: Testing"               "test and test_full profiles, nf-test, stub in CI."
mkmilestone "Phase 7: QC report"             "Deferred. Machine-readable pass/fail signals plus HTML."
mkmilestone "Phase 8: Release 1.0.0"         "Tag off main once the required path runs end to end."
mkmilestone "Backlog"                        "Bookmarks, upstream contributions, nice to haves, open questions."

# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------

echo "== Issues"
mkissue() {
    local title="$1" milestone="$2" labels="$3" body="$4"
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '  [dry-run] %-12s %s\n' "[$labels]" "$title"
        return
    fi
    gh issue create --repo "$REPO" \
        --title "$title" \
        --milestone "$milestone" \
        --label "$labels" \
        --body "$body"
}

M0="Phase 0: Freeze and diagnose"
M1="Phase 1: Scaffold"
M2="Phase 2: Preprocessing half"
M3="Phase 3: TMA path"
M4="Phase 4: Resource profiles"
M5="Phase 5: Containers"
M6="Phase 6: Testing"
M7="Phase 7: QC report"
M8="Phase 8: Release 1.0.0"
MB="Backlog"

# --- P0 correctness findings -----------------------------------------------

mkissue "P0: convert_to_spatialdata.py loads whole images into RAM" "$M0" "P0,metadata" \
"\`bin/convert_to_spatialdata.py\` calls \`tifffile.imread()\` then \`Image2DModel.parse()\`. It does not call \`sopa convert\`.

Consequences:
- Eager whole-image loading. Inputs are 5 GB to 100 GB; the process is configured at 8 GB escalating to 32 GB. A 100 GB image cannot pass through it.
- No multiscale pyramid. \`Image2DModel.parse\` without \`scale_factors\` writes a single scale level.
- Channel names overwritten with \`\"0\"\`, \`\"1\"\`, \`\"2\"\`. This is why \`cellpose_channels = '0'\`. Marker names never reach the SpatialData object.
- Physical pixel size dropped.

This undoes the reason sopa was chosen in the first place.

Fix: delete the script, vendor sopa's \`TO_SPATIALDATA\` verbatim, run \`sopa convert --technology ome_tif\`.

See ROADMAP.md §2 P0-1."

mkissue "P0: Coreograph runs docker run inside a process and fabricates data on failure" "$M0" "P0" \
"\`bin/run_coreograph.py\` shells out to \`docker run --platform linux/amd64 ... labsyspharm/unetcoreograph:2.4.6\` via \`subprocess.run(..., shell=True)\`.

There is no Docker daemon on the SLURM cluster, so this **always** fails and **always** reaches the fallback. The fallback crops the four corner quadrants of the image, each capped at 3200 px (\`min(3200, h // 2)\`), and names them \`1.tif\` to \`4.tif\`.

So with \`use_tma_dearray = true\` on the cluster, the pipeline emits four corner crops labelled as cores, silently. Core identity is a hard requirement, which makes this the most severe defect in the repository.

It is also nested containerisation: the process declares \`container 'labsyspharm/unetcoreograph:2.4.6'\` then tries to launch that image from inside it.

Fix: install the nf-core \`coreograph\` module, which invokes \`/app/UNetCoreograph.py\` directly. No fallback. If Coreograph fails, the run fails.

See ROADMAP.md §2 P0-2."

mkissue "P0: no process emits versions.yml" "$M1" "P0,nf-core" \
"Zero of twelve processes emit \`versions.yml\`. There is no provenance record anywhere in the pipeline, which is a direct hit on the top stated priority (transparency).

Resolved by vendoring sopa's modules and installing the mcmicro modules, both of which carry version capture blocks.

See ROADMAP.md §2 P0-4."

mkissue "P0: ASHLAR dfp/ffp ordering is unguarded" "$M2" "P0" \
"Ashlar requires positional correspondence between input images and illumination profiles.

The \`main.nf\` path for pre-computed \`dfp\`/\`ffp\` builds those lists via \`groupTuple()\`, which gives no ordering guarantee. Misordered profiles produce silently misregistered output rather than an error.

Fix: carry an explicit cycle index in the meta map, sort by it, and assert list lengths match before invoking Ashlar.

See ROADMAP.md §2 P0-5."

mkissue "P0: min_area hardcoded to 0 disables all object filtering" "$M1" "P0" \
"\`sopa segmentation cellpose ... --min-area 0\` disables small-object filtering entirely, admitting debris and nuclear fragments into the feature table. Confirmed arbitrary rather than deliberate.

Restoring \`argsCLI\` exposes \`min_area_pixels2\`. sopa's mIF presets give starting values: 38 for phenocycler at 20X, 400 for macsima.

Existing results should be reinterpreted accordingly.

See ROADMAP.md §2 P0-6."

# --- Phase 0 ---------------------------------------------------------------

mkissue "Commit AGENT_CONTEXT.md and ROADMAP.md" "$M0" "phase-0" \
"\`AGENT_CONTEXT.md\` is currently untracked (\`?? AGENT_CONTEXT.md\` in git status). Commit it alongside ROADMAP.md."

mkissue "Rename main to legacy and push" "$M0" "phase-0" \
"Current \`main\` is two commits (\`1dc4b9b init\`, \`fe56581 added: AGENTS.md\`) with no nf-core scaffolding.

Rename to \`legacy\` and push. It stays as a reference for what the parameters and Python glue did, and is never merged forward.

See ROADMAP.md §1 'Why the plan changed'."

mkissue "Diagnose Coreograph output: what does it produce and why does sopa reject it?" "$M0" "phase-0,diagnosis,metadata" \
"Read-only investigation on one real TMA. **This gates the Phase 3 design.** No fix in this issue.

Recollection is that \`technology = 'ome_tif'\` worked, and the failure was specifically Coreograph output into \`sopa convert\`, caused by TIFF formatting. \`bin/fix_core_ome_tiff.py\` sets \`axes='CYX'\`, \`photometric='minisblack'\`, \`ome=True\` and injects Channel names, which points at axis interpretation and missing OME channel metadata rather than pixel data.

Take one Coreograph core straight out of the container with no post-processing and record:

- [ ] \`tifffile.TiffFile(core).series[0].axes\` and \`.shape\`, and \`len(tif.pages)\`
- [ ] whether an OME-XML block exists, and whether it contains \`Channel\` elements and \`PhysicalSizeX\`
- [ ] whether the \`ImageDescription\` TIFF tag is present (\`tiffcomment\` errors without it)
- [ ] \`is_imagej\`, \`is_ome\`, \`photometric\` on page 0
- [ ] what \`dask_image.imread.imread(core).ndim\` returns, since that is what sopa branches on
- [ ] the exact traceback from \`sopa convert --technology ome_tif\` on the raw core

Do the same for the Ashlar output that fed Coreograph, so the comparison isolates what Coreograph changes.

Relevant sopa constraints:
\`\`\`python
if image.ndim == 4:
    assert image.shape[0] == 1, \"4D images not supported\"
elif image.ndim != 3:
    raise ValueError(f\"Number of dimensions not supported: {image.ndim}\")
\`\`\`
A single-channel core gives \`ndim == 2\` and raises. An ImageJ hyperstack can give \`ndim == 4\`.

Record findings in the repo.

See ROADMAP.md §2 P0-3 and §3 Phase 0."

mkissue "DECISION: pull the mcmicro metadata stack forward if Coreograph is a metadata problem" "$M0" "phase-0,decision,metadata" \
"Depends on the Coreograph diagnosis.

If the diagnosis shows the problem is metadata rather than pixel data, which the current evidence suggests, the §6 metadata stack stops being a bookmark and becomes the fix. In that case pull it into Phase 2 rather than deferring:

- \`BFTOOLS_SHOWINF\` on the cores tells you precisely what is missing, using the same tool that will later repair it.
- \`OMEVALIDATION\` already raises \`Images are missing pixel physical size metadata\`, so the loud failure comes free.
- \`tiffcomment -set\` repairs the OME-XML at the producing step, satisfying the no-post-hoc-Python preference properly rather than by exception.
- Channel names and pixel size get solved once, for both the stitched image and the cores, instead of twice.

Cost of pulling forward: Phase 2 grows, and the \`-stub\` gap in \`UPDATE_FROM_OME\` arrives earlier.
Cost of not pulling forward, if the diagnosis points this way: building a throwaway Coreograph fix and then replacing it.

Decide once the diagnosis is in hand, not before.

See ROADMAP.md §3 Phase 0 decision branch."

mkissue "Move check_qupath_paquo.py to tests/ as an acceptance check" "$M0" "phase-0,testing" \
"\`bin/check_qupath_paquo.py\` automates loading cores into QuPath to verify metadata makes them ingestable. It does not appear in the workflow.

It is a good test and a bad pipeline step. Reuse it in the Coreograph diagnosis, then move it to \`tests/\`.

See ROADMAP.md §3 Phase 0."

# --- Phase 1 ---------------------------------------------------------------

mkissue "Copy nf-core/sopa:dev tree at c2b4e5f with fresh git history" "$M1" "phase-1,nf-core" \
"Clone as a scaffold, not a fork. Fresh \`git init\`, no sopa remote, no inherited TEMPLATE.

Initial commit message body records source repository, SHA (\`c2b4e5fe1f5291a3f079e55859cd2f42e588e324\`) and retrieval date.

Rationale: rebranding guarantees automated upstream merges conflict regardless of whether a remote exists, so the fork obligation buys nothing. Manual diffs against the local sopa clone at \`~/Jose_BI/1_Repositories/sopa\` are the realistic upgrade path either way.

See ROADMAP.md §1 'Why the plan changed'."

mkissue "Rebrand: strip nf-core branding and org CI" "$M1" "phase-1,nf-core" \
"One commit. Rename the pipeline to \`imagingpipeline\` (lowercase, no separators, since Nextflow uses the repo name).

- [ ] strip \`NFCORE_SOPA\`
- [ ] remove \`assets/nf-core-sopa_logo_*\` and \`docs/images/\`
- [ ] remove \`CODE_OF_CONDUCT.md\` and \`ro-crate-metadata.json\`
- [ ] remove nf-core org CI from \`.github/\`
- [ ] strip branding from \`README.md\` and \`utils_nfcore_sopa_pipeline\`

This pipeline must not be branded as nf-core (AGENT_CONTEXT.md §1)."

mkissue "Delete out-of-scope features, one commit each" "$M1" "phase-1" \
"One commit per feature so each deletion is a documented decision, not a bulk purge.

- [ ] \`baysor\`
- [ ] \`comseg\`
- [ ] \`proseg\`
- [ ] \`stardist\`
- [ ] \`spaceranger\` and the visium_hd path
- [ ] \`scanpy_preprocess\`
- [ ] \`fluo_annotation\`
- [ ] \`make_transcript_patches\`
- [ ] \`explorer_raw\`
- [ ] their \`conf/predefined/*\` configs, schema entries and nf-tests

Keep: \`TISSUE_SEGMENTATION\`, cellpose, and the phenocycler/macsima/hyperion mIF presets."

mkissue "Housekeeping: LICENSE, CITATIONS.md, CHANGELOG.md" "$M1" "phase-1,nf-core" \
"- [ ] MIT \`LICENSE\` with attribution to sopa and mcmicro
- [ ] \`CITATIONS.md\` crediting sopa, mcmicro and every underlying tool
- [ ] \`CHANGELOG.md\` with semantic versioning

Both source projects are MIT; attribution is a licence requirement and part of the transparency goal (AGENT_CONTEXT.md §4)."

mkissue "Vendor nf-core AGENTS.md verbatim with provenance" "$M1" "phase-1,nf-core" \
"Vendor the nf-core community \`AGENTS.md\` verbatim rather than linking, recording source URL, commit SHA and retrieval date so it can be diffed against upstream later.

\`AGENT_CONTEXT.md\` layers on top and takes precedence where they conflict.

Source: https://github.com/nf-core/agents/blob/main/resources/pipeline/AGENTS.md"

mkissue "Create TEMPLATE orphan branch for nf-core pipelines sync" "$M1" "phase-1,nf-core" \
"Generate with \`nf-core pipelines create\` answering **no** to 'is this an nf-core pipeline?', which strips branding and org CI while keeping the skeleton and linting.

Put the output on a \`TEMPLATE\` orphan branch so \`nf-core pipelines sync\` keeps working.

Note the template gap: sopa:dev sits on tools 4.0.3, current is 4.1.0.

Never write to the TEMPLATE branch afterwards."

mkissue "Set a real min_area_pixels2 default in the schema" "$M1" "phase-1" \
"Currently hardcoded to 0 in the script body, which disables filtering. Set a defensible default via \`nf-core pipelines schema build\`.

Starting points from sopa's mIF presets: 38 (phenocycler 20X), 400 (macsima).

Related to the P0 min_area issue."

mkissue "Scaffold the QC report hook" "$M1" "phase-1" \
"QC is deferred to Phase 7, but scaffold the module and channel wiring now so the hook exists and the DAG shape is settled.

See ROADMAP.md §3 Phase 7."

mkissue "Phase 1 exit: lint, prek and stub run all pass" "$M1" "phase-1,testing,nf-core" \
"Before the PR:

- [ ] \`nf-core pipelines lint\` clean, errors and all solvable warnings
- [ ] \`prek\` clean
- [ ] \`-stub\` run completes on the \`test\` profile, cellpose path only

Compliance comes from tooling, not from following guidelines by eye (AGENT_CONTEXT.md §8)."

# --- Phase 2 ---------------------------------------------------------------

mkissue "Install nf-core modules: basicpy, backsub, ashlar, coreograph" "$M2" "phase-2,nf-core" \
"\`nf-core modules install <name>\`. One commit each, titled \`Install nf-core module {name}\`.

\`modules.json\` is the lockfile: it pins an exact nf-core/modules commit SHA per module. Always commit it.

SHAs currently pinned in mcmicro's modules.json for reference: ashlar \`c7c25b63\`, backsub \`41dfa3f7\`, basicpy \`a46512fa\`, coreograph \`41dfa3f7\`."

mkissue "Patch backsub to v0.5.1" "$M2" "phase-2,nf-core,containers" \
"The nf-core module ships \`ghcr.io/schapirolabor/background_subtraction:v0.4.1\`. You run \`v0.5.1\`.

- [ ] edit the container directive
- [ ] update the \`versions.yml\` capture block **in the same commit** (a stale hardcoded version makes provenance silently wrong)
- [ ] \`nf-core modules patch backsub\`
- [ ] verify an amd64 image for the tag exists
- [ ] commit the resulting \`.diff\` and \`modules.json\`

The patch survives \`nf-core modules update\` and produces a visible conflict rather than a silent clobber.

Note: backsub has no \`environment.yml\`, so there is no bioconda recipe to fix upstream. The nf-core module bump is the only route."

mkissue "Patch coreograph to 2.4.6" "$M2" "phase-2,nf-core,containers" \
"The nf-core module ships \`docker.io/labsyspharm/unetcoreograph:2.2.9\`. You run \`2.4.6\`, so installing the module is a **downgrade**.

- [ ] edit the container directive
- [ ] update the hardcoded \`VERSION\` string in the versions block in the same commit
- [ ] \`nf-core modules patch coreograph\`
- [ ] verify an amd64 image for 2.4.6 exists
- [ ] check whether 2.4.6 alone resolves the OME formatting problem from the Phase 0 diagnosis

Note: coreograph has no \`environment.yml\`, container-only and amd64-only."

mkissue "Build PREPROCESS_IMAGES subworkflow" "$M2" "phase-2" \
"\`subworkflows/local/preprocess_images\`:

1. illumination correction (required)
2. stitching and registration (required)
3. optional background subtraction (\`use_backsub\`, default false)
4. optional TMA dearray (\`use_tma_dearray\`, default false)

Optional steps are booleans in the schema with \`default: false\` so they self-document via \`--help\`.

The handoff boundary to the sopa half is a single stitched OME-TIFF. Keep it clean."

mkissue "Fan BASICPY out per cycle" "$M2" "phase-2" \
"Current \`BASICPY\` loops over all cycles inside one task via a Groovy \`collect\` that joins shell commands.

Consequences: no parallelism, and one bad cycle fails the whole slide with no error isolation.

Fix: one task per cycle."

mkissue "Assert channel names survived conversion" "$M2" "phase-2,metadata" \
"sopa's \`ome_tif\` reader falls back to integer channel names with only a \`log.warning\`:

\`\`\`python
if len(channel_names) != len(image):
    channel_names = [str(i) for i in range(len(image))]
    log.warning(f\"Channel names couldn't be read. Using {channel_names} instead.\")
\`\`\`

For unattended runs on colleagues' data, silently losing every marker name is not acceptable. Add a check after \`TO_SPATIALDATA\`.

**Caveat:** until the §6 metadata bookmark is picked up, channel names *will* be integers, so a hard error here blocks Phase 3. Make the warning-versus-error choice consciously.

Blocked by the metadata bookmark issue."

mkissue "Run nf-core pipelines schema build" "$M2" "phase-2,nf-core" \
"Never hand-edit \`nextflow_schema.json\`. Use \`nf-core pipelines schema build\`.

\`-params-file params.yml\` is the primary interface, so the schema is what validates it."

mkissue "Write stub blocks for every local module" "$M2" "phase-2,testing" \
"\`-stub\` is the primary fast feedback loop, and the only meaningful local test loop given amd64-only containers on an M3 Mac.

Rule: **whenever a module's outputs change, update its stub block in the same commit.** Stub blocks rot, and a stale stub passing while the real run fails is worse than no test."

# --- Phase 3 ---------------------------------------------------------------

mkissue "Fix Coreograph output at the producing step" "$M3" "phase-3,metadata" \
"Design follows from the Phase 0 diagnosis. Preference order:

1. container bump to 2.4.6 alone, if that resolves it
2. a patched module with a corrected write step
3. an upstream UNetCoreograph fix

No \`bin/fix_core_ome_tiff.py\`. Post-module Python is permitted as an escape hatch, but a better tool exists here (\`tiffcomment -set\`), so use it.

Blocked by the Coreograph diagnosis issue."

mkissue "Rename cores to carry unambiguous IDs before conversion" "$M3" "phase-3" \
"sopa derives element names from filenames:

\`\`\`python
image_name = Path(path).absolute().name.split(\".\")[0]
\`\`\`

Coreograph emits \`1.tif\`, \`2.tif\`, so element names become \`1\`, \`2\`. Requirement is unambiguous core IDs in element names.

Rename to something like \`{sample}_core_{n}.ome.tif\` before conversion, using a \`mv\` loop in the patched module (shell at the producing step, within constraints).

Use Coreograph's \`centroidsY-X.txt\` and \`TMA_MAP.tif\` so the core-ID-to-physical-position mapping is recorded rather than inferred."

mkissue "Gate MERGE_SPATIALDATA on use_tma_dearray" "$M3" "phase-3,P1" \
"\`MERGE_SPATIALDATA( ch_grouped_cores )\` is called at the top level of \`SOPA_SPATIAL\` with no \`if\`. For non-TMA input it merges a single sample with itself.

Merging is only wanted for TMA datasets; otherwise you would juggle hundreds of SpatialData objects."

mkissue "Rewrite the TMA merge to write incrementally" "$M3" "phase-3,P1" \
"\`merge_spatialdata.py\` accumulates every core's images, shapes and tables in Python dicts, then calls \`.write()\` once. With hundreds of cores this exhausts RAM.

Images are already lazy: \`sd.read_zarr\` returns dask-backed arrays, so holding them is cheap. The blowup is the single terminal \`.write()\` materialising everything at once.

Fix: write an empty SpatialData to the target Zarr first, then loop and \`SpatialData.write_element()\` one element at a time, letting each core's dask graph evaluate and release before the next. Peak memory becomes one core rather than all cores.

Tables are the exception: spatialdata does not support incremental partial changes to a table, so per-core AnnData must be concatenated in memory. Tolerable at one row per cell. Keeping tables as separate per-core elements is the fallback and preserves core identity more cleanly.

Verify with \`/usr/bin/time -v\` peak RSS on the real TMA, not by inspection."

mkissue "Fail loudly if pixel size is lost, no magic default" "$M3" "phase-3,metadata" \
"\`fix_core_ome_tiff.py\` silently defaults to \`0.65 µm/px\` when resolution tags are unreadable, turning a magic number into data.

If pixel size is genuinely lost by Coreograph, that is a producer-side fix. It must fail loudly. If a default is unavoidable, use \`1.0\` µm/px as an obviously-wrong sentinel and surface a warning that reaches the report.

Note \`OMEVALIDATION\` already raises \`Images are missing pixel physical size metadata\`, so adopting the metadata stack gives this for free."

# --- Phase 4 ---------------------------------------------------------------

mkissue "Create small/medium/huge size profiles with TODO resource markers" "$M4" "phase-4" \
"Inputs range 5 GB to 100 GB. Rather than one guessed resource set, three profiles selected per dataset.

- [ ] \`conf/size_small.config\`
- [ ] \`conf/size_medium.config\`
- [ ] \`conf/size_huge.config\`

Every \`cpus\`, \`memory\` and \`time\` value gets a \`TODO\` marker to fill in from real run data rather than a guess."

mkissue "Replace max_memory and max_cpus with resourceLimits" "$M4" "phase-4,nf-core" \
"\`nextflow.config\` sets \`max_memory = '32.GB'\` and \`max_cpus = 8\`. Both deprecated in the nf-core template since 3.0 in favour of \`resourceLimits\`."

mkissue "Add conf/mdc.config institutional profile" "$M4" "phase-4" \
"SLURM setup, and \`NXF_SINGULARITY_CACHEDIR\` pointing at the shared filesystem path rather than \`\$HOME\`, set in institutional config rather than passed per run."

mkissue "Review errorStrategy retry codes against nf-core base.config" "$M4" "phase-4,P1,nf-core" \
"Current: \`errorStrategy = { task.exitStatus in [137, 140, 7, 125] ? 'retry' : 'finish' }\`, \`maxRetries = 3\`, with escalating memory on ASHLAR and TO_SPATIALDATA only.

Described as barebones and not tuned against real failures. Compare against nf-core \`base.config\` conventions. Note \`base.config\` must not be edited directly."

# --- Phase 5 ---------------------------------------------------------------

mkissue "Restore upstream container URIs, remove hardcoded .sif paths" "$M5" "phase-5,containers" \
"\`/fast/AG_Coscia/software/singularity/python_sopa.sif\` is hardcoded in all 8 processes in \`sopa_spatial.nf\` (plus once in \`nextflow.config\`), with the upstream container directive commented out above each.

Restore upstream's dual singularity/docker ternary. Pre-staged SIFs in the shared \`NXF_SINGULARITY_CACHEDIR\` give the same no-network behaviour without baking the cluster into module bodies."

mkissue "Add a container manifest to version control" "$M5" "phase-5,containers" \
"A script or list of every image URI in the pipeline, sitting alongside \`modules.json\` as a reviewable record.

Rules it supports: never introduce a runtime container pull or launch-time network dependency; all images pre-staged; no Wave resolution at launch."

mkissue "Document the container pre-staging workflow" "$M5" "phase-5,containers" \
"On a well-connected machine:

\`\`\`
nf-core pipelines download <pipeline> -r <tag> --container-system singularity
\`\`\`

then rsync the SIFs into the shared cache. The cluster has intermittently poor internet and frequently fails on-demand pulls.

Never write to the shared \`NXF_SINGULARITY_CACHEDIR\` from an agent; colleagues depend on it."

# --- Phase 6 ---------------------------------------------------------------

mkissue "Create a test profile with tiny input" "$M6" "phase-6,testing" \
"Deliberately tiny: a cropped two-channel tile, and a four-core TMA fixture. Should run in a few minutes and exercise basic functionality."

mkissue "Create a test_full profile" "$M6" "phase-6,testing" \
"Real dataset, triggering all pipeline functionality. Run before tagging a release."

mkissue "Set up a test data repository" "$M6" "phase-6,testing" \
"\`nf-core/test-datasets\` requires org membership, so test data lives in a small repo of your own."

mkissue "Add stub run and nf-test to CI" "$M6" "phase-6,testing" \
"- [ ] \`-stub\` run in CI
- [ ] \`nf-test test tests/\`
- [ ] at least one test case (nf-core requirement)

If Nextflow still tries to stage containers in stub mode, combine \`-stub\` with the \`local\` executor.

Never edit snapshots by hand; regenerate with \`--update-snapshot\` and only on the same CPU architecture as CI."

mkissue "Wire check_qupath_paquo.py in as a TMA acceptance check" "$M6" "phase-6,testing,metadata" \
"Run against the four-core TMA fixture to assert cores remain ingestable by QuPath.

Depends on the Phase 0 move of the script into \`tests/\`."

# --- Phase 7 ---------------------------------------------------------------

mkissue "Design machine-readable QC pass/fail signals" "$M7" "phase-7,decision" \
"Deferred by decision. The HTML report for a microscopist is the stated deliverable, but unattended runs on colleagues' data also need machine-readable pass or fail signals, not only something to eyeball.

Candidate signals:
- cell count per core
- mean and saturated-pixel fraction per channel
- Ashlar registration residual
- fraction of patches with zero cells
- whether channel names are real rather than integers

**Acceptance thresholds need to come from Jose.**

Consider adopting mcmicro's \`PRELUDE\` ahead of this: it is a pre-flight gate that catches samplesheet, markersheet and OME metadata inconsistencies in seconds, before Ashlar runs. For unattended runs that may be worth more than the report it would precede."

# --- Phase 8 ---------------------------------------------------------------

mkissue "Tag 1.0.0 off main" "$M8" "phase-8,nf-core" \
"Tag once illumination correction, stitching/registration and segmentation run end to end, even with optional steps unfinished. A tag is what makes \`-r 1.0.0\` reproducible for colleagues.

- [ ] \`nf-core pipelines lint --release\` clean
- [ ] \`test_full\` passes
- [ ] release notes state that quantification is nuclear-only, since \`expand_radius_ratio\` is deferred"

# --- Backlog: bookmark -----------------------------------------------------

mkissue "BOOKMARK: channel names and physical pixel size via the mcmicro metadata stack" "$MB" "bookmark,metadata" \
"Not scheduled. Recording the route so it is not rediscovered later. May be pulled forward, see the Phase 0 decision issue.

## What sopa can and cannot do

\`sopa convert --technology ome_tif\` is lazy and builds a pyramid, but:
- channel names come from OME-XML **only**, with a silent integer fallback. No parameter accepts a channel list.
- physical pixel size is never read. The image gets \`transformations={\"pixels\": Identity()}\`.

## What mcmicro already has

| Piece | Location | What it does |
|---|---|---|
| \`BFTOOLS_SHOWINF\` | nf-core/modules, installable | \`showinf -nopix -no-upgrade -omexml-only\` per cycle. Has \`environment.yml\` (\`bioconda::bftools=8.0.0\`) and a biocontainer. |
| \`OMEVALIDATION\` | mcmicro modules/local, vendorable | Groovy \`exec:\` block. Parses XML with \`XmlSlurper\`, extracts tile count, tile size, \`PhysicalSizeX/Y\` and units, validates presence and consistency. |
| \`UPDATE_FROM_OME\` | mcmicro subworkflows/local | Joins markersheet against OME-XML, computes cumulative \`channel_number\` offsets across cycles, checks marker count vs channel count, errors if \`exposure_time\` null when backsub enabled. |
| \`PRELUDE\` | mcmicro subworkflows/local | MultiQC-ready summaries of XML, markersheet, samplesheet, with error reporting. |

\`OMEVALIDATION\`'s nf-tests already assert \`Images are missing pixel physical size metadata\`, which is exactly the loud failure wanted in place of the 0.65 default.

## The writing side

\`\`\`
tiffcomment sample.ome.tif                           # extract
tiffcomment -set 'newmetadata.xml' sample.ome.tif    # inject
\`\`\`

So the shape is: \`BFTOOLS_SHOWINF\` → \`UPDATE_FROM_OME\` reconciles with markers.csv → \`tiffcomment -set\` writes corrected XML back. All at the producing step, tool-level, no Python.

## Caveats to check when picked up

- \`tiffcomment\` **errors if the \`ImageDescription\` TIFF tag is absent.** Documented limitation, likely relevant to Coreograph cores.
- \`UPDATE_FROM_OME\` contains \`if (workflow.stubRun) { return }\`, so it is skipped entirely in stub runs. Since \`-stub\` is the primary feedback loop, adopting it adds a path \`-stub\` never exercises.
- \`OMEVALIDATION\` uses a Groovy \`exec:\` block: head node, no container, no \`versions.yml\`. Cannot be \`nf-core modules install\`ed.
- bftools is Java, so \`bftools:8.0.0--hdfd78af_0\` may run on Apple Silicon. Worth five minutes; would be a rare locally-testable module.
- mcmicro's stack assumes the multi-cycle samplesheet shape (\`cycle_number\`, \`channel_count\`). Fine for the mIF path, needs thought for single-prestitched-image input.

See ROADMAP.md §6."

# --- Backlog: open decisions ----------------------------------------------

mkissue "DECISION: physical pixel size in the Zarr, or only in Explorer output?" "$MB" "decision,metadata" \
"You want pixel size in the image metadata. sopa does not put it there: it carries physical scale as \`params.pixel_size\` consumed at Explorer export, with the image on \`Identity()\` into a \`\"pixels\"\` coordinate system.

1. **Accept sopa's model.** Set \`params.pixel_size\`; physical scale exists only in Explorer output. No divergence, but the Zarr is not self-describing and napari will show the wrong scale.
2. **Edit vendored \`TO_SPATIALDATA\`** to read \`PhysicalSizeX\` and emit a \`Scale\` transformation into a microns coordinate system. Spatialdata-native and self-describing, and a good upstream contribution. But it diverges from stock sopa output, affecting diffability.
3. **Both.**

Leaning to 3, with the \`Scale\` change offered upstream so the divergence is temporary. Not actionable until the metadata bookmark is picked up, since \`OMEVALIDATION\` is what would supply the value."

mkissue "DECISION: adopt mcmicro's PRELUDE as a pre-flight gate?" "$MB" "decision,metadata" \
"\`PRELUDE\` validates samplesheet, markersheet and OME metadata consistency in seconds, before Ashlar runs.

For unattended runs on colleagues' data, catching a marker count mismatch immediately rather than after a six-hour Ashlar job is arguably worth more than the QC report it would precede.

Cost: adopting it means accepting mcmicro's multi-cycle samplesheet shape.

Decide whether this comes before Phase 7."

# --- Backlog: P1 cleanup ---------------------------------------------------

mkissue "P1 cleanup checklist" "$MB" "P1" \
"Smaller defects, mostly resolved as a side effect of vendoring upstream modules. Tracked here so none is lost.

- [ ] \`params.coreograph_args\` is computed into \`def args\` and never used. The configured \`--channel 0 --downsampleFactor 3 --buffer 2\` has no effect.
- [ ] Cellpose hardcodes \`--no-gpu\` while the \`slurm\` profile sets \`containerOptions '--nv'\`. The profile enables GPU passthrough and the command line disables it.
- [ ] \`containerOptions '--platform linux/amd64'\` on \`COREOGRAPH\` is a Docker flag and fails under Apptainer.
- [ ] \`groupKey\` is dropped. Upstream uses \`groupKey(meta.sdata_dir, n_patches)\` so groups release once the expected count arrives; plain \`groupTuple(by: 0)\` blocks until the channel completes, serialising multi-sample runs.
- [ ] \`RESOLVE_CELLPOSE\` uses \`cp\` where upstream uses \`mv\`, doubling peak disk.
- [ ] \`publishDir\` is set in process bodies with \`mode: 'copy'\` hardcoded, rather than in \`conf/modules.config\` with \`params.publish_dir_mode\`, which is not defined at all.
- [ ] \`bin/\` scripts are invoked as \`\$projectDir/bin/script.py\` rather than by name on \`PATH\`.
- [ ] \`ext.args\` and \`ext.prefix\` conventions are unused; every flag is interpolated in script bodies.

See ROADMAP.md §2 P1 findings."

# --- Backlog: upstream -----------------------------------------------------

mkissue "UPSTREAM: bump backsub to v0.5.1 in nf-core/modules" "$MB" "upstream,nf-core" \
"A few lines. Removes the need for a local patch.

No \`environment.yml\` on this module, so it is a container tag bump rather than a bioconda recipe fix."

mkissue "UPSTREAM: bump coreograph to 2.4.6 in nf-core/modules" "$MB" "upstream,nf-core" \
"The nf-core module is at 2.2.9. Container-only, no conda recipe, so this is a container tag bump."

mkissue "UPSTREAM: Scale transformation for pixel size in sopa's ome_tif reader" "$MB" "upstream,metadata" \
"Depends on the pixel size decision. If options 2 or 3 are chosen, offer the change upstream so the divergence in the vendored module is temporary."

mkissue "UPSTREAM: make sopa fail rather than warn on channel-name fallback" "$MB" "upstream,metadata" \
"sopa's \`ome_tif\` reader emits \`log.warning\` and substitutes integer channel names. For unattended pipeline use a hard failure, or at minimum an opt-in strict mode, would be safer.

Small change, broad benefit."

mkissue "UPSTREAM: contribute TMA support to nf-core/sopa" "$MB" "upstream" \
"Core-aware element naming and the merge step. sopa has no equivalent, and this is the most novel piece of this pipeline.

Depends on Phase 3 landing and the merge being memory-sane."

# --- Backlog: nice to haves ------------------------------------------------

mkissue "NICE TO HAVE: Ashlar rotation-correction fork provenance" "$MB" "upstream,containers" \
"\`josenimo/jose_ashlar:1.21.0\` derives from \`jmuhlich/ashlar\` branch \`rotation-correction\`, 27 commits ahead of \`ashlar/master\` and 1 behind. The feature is rotation correction.

Worth noting: jmuhlich is Ashlar's maintainer, so this is the maintainer's own feature branch, not a third-party fork. Eventual upstreaming is likely without your effort, which makes vendoring genuinely temporary rather than a permanent liability.

Deferred by decision. Two cheap things when there is time:
- [ ] check whether \`rotation-correction\` has since merged to \`ashlar/master\`
- [ ] put the Dockerfile in version control so \`josenimo/jose_ashlar:1.21.0\` is reproducible rather than an opaque tag

Note this is **not** a \`nf-core modules patch\` case. Patch is for version bumps; a code fork needs vendoring to \`modules/local/ashlar\` with provenance documented.

Ashlar is the only one of the four mcmicro modules with a conda recipe, so it is the only one with a bioconda upstreaming route."

mkissue "Verify remaining open items" "$MB" "decision" \
"Not yet checked, and load-bearing.

- [ ] Wave and Seqera Containers config keys, free-tier limits and image retention policy. Most likely of the AGENT_CONTEXT.md §10 items to have moved.
- [ ] Whether an institutional registry exists at MDC (Harbor, GitLab, Artifactory) to mirror into, given the flaky cluster network.
- [ ] Whether the current Nextflow version stages containers during \`-stub\` runs.
- [ ] Whether \`bftools:8.0.0--hdfd78af_0\` runs on Apple Silicon.
- [ ] Whether \`jmuhlich/ashlar\` \`rotation-correction\` has merged upstream since.
- [ ] Whether nf-core/mcmicro's segmentation still breaks on very large images (experience is ~2 years old; less critical since the sopa path is chosen regardless).

Confirmed already: nf-core/tools is at 4.1.0 (29.07.2026); sopa:dev sits on template 4.0.3."

echo
if [[ $DRY_RUN -eq 1 ]]; then
    echo "Dry run complete. Nothing was created."
    echo "Run without --dry-run to create for real."
else
    echo "Done. Review at https://github.com/${REPO}/issues"
fi
