# Decisions

Why the pipeline is built the way it is. Each entry exists because the question came up, was
settled with evidence, and would otherwise be asked again.

## Architecture

**Two upstream projects, one handoff.** Preprocessing from nf-core/mcmicro, everything from
segmentation onward from nf-core/sopa, meeting at a single stitched OME-TIFF. sopa was chosen
for the downstream half because its segmentation is size independent: it tiles, segments each
tile, and parallelises. Inputs here run 5–100 GB, so that property outranks everything else.

**Cloned, not forked.** Rebranding guarantees merge conflicts with upstream anyway, so the sopa
tree was imported at `c2b4e5f` with fresh history. The import was verified byte-identical to
upstream by tree hash before anything was changed.

**Not an nf-core pipeline.** It follows nf-core conventions because they genuinely help with
reproducibility, and to keep open the option of contributing modules upstream. Divergences from
the template are listed with reasons in `.nf-core.yml`.

## The TMA path

**Merge at the very end.** Each core runs the whole downstream half independently and only the
results are combined. Segmenting many small dense objects scales better than one large sparse
one, and per-core QC reports survive.

**`MERGE_SPATIALDATA` writes one element at a time.** Images read from Zarr are dask-backed, so
holding references is cheap; it is a single terminal `.write()` that materialises every core at
once. Writing incrementally makes peak memory one core rather than all of them — measured at
614 MB for four cores.

**A core that cannot be read is a hard failure.** The predecessor caught every exception,
printed a warning and continued, so a slide could merge 78 of 80 cores and exit 0.

**Element naming is `{core_id}__{original}`**, with the prefix skipped when the element is
already named for its core. The separator is doubled because core IDs contain single
underscores, and troubleshooting needs an unambiguous split point.

**It chains off `REPORT`, not the shared upstream channel.** The sopa modules mutate the Zarr in
place and `REPORT` deletes `.sopa_cache` from it, so a concurrent reader would race a writer.

## Channel names

Ashlar writes no marker names into its OME-XML. Backsub writes them correctly. Coreograph
discards them again. So sopa reads the OME channel *IDs* and the feature matrix comes out with
columns called `Channel:0:0`.

**Fixed in the Zarr, immediately after conversion.** `SET_CHANNEL_NAMES` sets them from the
marker sheet using `SpatialData.set_channel_names(..., write=True)`. Free at any image size:
channel names live in about 5 KB of group metadata at `images/<element>/zarr.json`, not
alongside the pixels. The table inherits them, because `AGGREGATE` reads names off the image.

**The OME-TIFF is left alone.** `tiffcomment -set` patches the header in constant time — 13
bytes changed on a 2.7 GB file — but a Nextflow task must not mutate its staged input, since
that input is a symlink into the upstream task's work directory and modifying it breaks the
immutability `-resume` depends on. Avoiding that means copying the whole image, which for a
100 GB slide costs more than named channels in QuPath are worth.

**nf-core/mcmicro never embeds names at all**, passing `markers.csv` to `mcquant` as
`--channel_names`. sopa has no equivalent hook, so the names have to be in the object.

**The guard that checked for this was removed.** It grepped sopa's log for "Channel names
couldn't be read", a message that only fires when sopa finds *no* names. It found the IDs, so
the guard never fired and `require_channel_names` gave false confidence. Checking the property
beats checking a proxy for it.

## Pixel size

Not written into the Zarr. sopa carries physical scale as a parameter consumed at export, with
the image on `Identity()`. Removing the Xenium Explorer export eliminated that option, and
SpatialData's alternative — an extra coordinate system — is a poor fit. Redefining `global`
would silently reinterpret `patch_width_pixel` and `min_area_pixels2` as microns. Images stay
in pixel units; Ashlar does preserve `PhysicalSizeX` in the OME-TIFF.

## Parameters

**`patch_width_pixel` is not computed for you.** It decides whether segmentation parallelises
at all, and it affects results at patch boundaries as well as runtime, so an automatic value
would mean the same slide segmenting differently on different hardware. Guidance and a table
are in [usage.md](usage.md).

**Size profiles are one file, not three.** Three near-identical files would have to be kept in
step by hand. `conf/sizes.config` declares its own `profiles` scope, merged by Nextflow.

**Tiled segmentation is deliberately not scaled by size profile.** `PATCH_SEGMENTATION_*` cost
is set by `patch_width_pixel`, not slide size. A larger slide should mean more tasks, not bigger
ones — scaling it would discard the size independence sopa was chosen for.

## Containers

**Nothing is pulled at run time.** The cluster's connectivity is intermittent and a pull that
fails three hours in wastes the run and the queue slot. `containers.tsv` is generated and kept
current by a pre-commit hook, and `docs/containers.md` covers pre-staging.

**The cache check computes Nextflow's exact filename.** An earlier version matched on tool name
and version appearing anywhere in a directory listing, and reported Coreograph 2.4.6 as present
when the cache held it under a different URI's name. Same image, same version, and Nextflow
still went to the network mid-run.

## Testing

**Properties, not checksums.** Cellpose output shifts with version and hardware, so a snapshot
of segmentation results fails for reasons unrelated to this pipeline. Channel names, element
names and patch counts cannot drift; cell count gets ±2%.

**Stub tests target the subworkflow, not the pipeline.** The pipeline entry point needs a
samplesheet whose relative paths resolve against a directory nf-test controls. The workflow
block is Groovy and can use `${projectDir}` directly.

**The fixture lives outside the repository.** 43 MB of binary that git would keep forever,
against a 3 MB repo. Located by `HISTO_FIXTURE`.

**A stub run cannot detect an incomplete commit.** Nextflow reads the working tree; git records
something else. Both diverged once, when a bare `local/` in `.gitignore` matched
`modules/local/` at any depth and a new module went missing from its own commit while the
workflow including it committed fine. `tools/clone_check.sh` runs the pipeline from a fresh
clone, which is the only check that sees what was actually committed.

## Recurring lessons

**Validation that has never been watched to fail is not validation.** An `assert` inside a
Nextflow channel operator is swallowed; `error()` is the reliable form. A guard keyed on a log
message holds only while the correlation holds.

**Make the value self-explanatory rather than adding code to explain it.** An unset
`HISTO_FIXTURE` yields the path `HISTO_FIXTURE_IS_NOT_SET/samplesheet_fixture.csv`, so the
existing `exists` check reports something legible. A value cannot break; logic can — the guard
this replaced was itself invalid config syntax.

**Error messages routinely point somewhere other than the cause.** An unset variable reported
as a missing parameter, a numeric string as a type error, a full `/tmp` as no space on device,
a dropped profile as a missing parameter. `nextflow config . -profile X` costs a second and
separates "the profile is not loading" from "the pipeline is wrong".

**Version-proofing one side of a coupling is half a job.** The Coreograph module patch was made
extension-agnostic across 2.2.9 and 2.4.6; the code parsing its output filenames was not, and
`.ome` survived into every core ID.
