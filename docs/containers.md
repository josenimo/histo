# Containers

This pipeline never pulls an image at run time. Every image is fetched in advance, on a machine with
working internet, and placed in the shared Singularity cache before any job is submitted.

That is not a preference. The cluster's connectivity is intermittent, and a pull that fails three
hours into a run wastes the run and the queue slot. A launch-time network dependency — including
resolving images through Wave — is treated as a defect.

## What the pipeline needs

[`containers.tsv`](../containers.tsv) at the repository root lists every image, one row per image
rather than per module, because several modules share one. It records the Singularity URI, the Docker
URI, the conda specification the image was built from, and which modules use it.

It is generated, not written:

```bash
tools/container_manifest.py            # rewrite it
tools/container_manifest.py --check    # fail if stale; runs as a pre-commit hook
```

Regenerate it after adding or removing a module, or bumping a container.

**Three images are Docker-only.** `basicpy`, `coreograph` and `backsub` come from mcmicro and have no
BioContainers Singularity build, so their `singularity_uri` column is empty. They have to be converted
from Docker rather than downloaded directly, which is slower and subject to Docker Hub rate limiting.
Budget for that.

## Fetching

On a well-connected Linux machine:

```bash
nf-core pipelines download josenimo/histo \
    -r <tag> \
    --container-system singularity \
    --outdir ~/histo-download
```

This resolves every image the pipeline declares and writes the SIFs alongside the pipeline code.

Cross-check what it fetched against the manifest. They should agree, and if they do not, the manifest
generator has a parsing bug rather than the download being wrong:

```bash
nextflow inspect . -profile singularity | grep -o '"container": "[^"]*"' | sort -u
```

## Staging into the shared cache

`NXF_SINGULARITY_CACHEDIR` points at a **shared filesystem path** that colleagues also use. It is set
in shell configuration and in the institutional Nextflow config, and is never passed per run.

> [!WARNING]
> Never delete from or overwrite files in the shared cache. Other people's running jobs depend on
> them. Copy in only what is missing.

Check first, copy second:

```bash
# what is already there
ls "$NXF_SINGULARITY_CACHEDIR"

# copy in only new files, never overwriting an existing one
rsync -av --ignore-existing ~/histo-download/singularity-images/ "$NXF_SINGULARITY_CACHEDIR/"
```

`--ignore-existing` rather than plain `rsync` is deliberate: an image already in the cache is one a
colleague may have a job attached to right now, and replacing it mid-run is how you break someone
else's week.

## Building an image

Only when no suitable image exists. Start from a micromamba or conda-forge base, pin exact versions,
and build for the cluster's architecture rather than your laptop's:

```bash
docker buildx build --platform linux/amd64 -t ghcr.io/<user>/<tool>:<version> .
```

Building a SIF directly needs Linux with root or fakeroot, so it generally cannot be done on macOS.
Push to `ghcr.io` or `quay.io`, then fetch it back through the normal pre-staging route above so that
the cache holds exactly what the pipeline will ask for.

## Why not run containers locally

The development laptop is macOS on Apple Silicon, `linux/arm64`. Essentially all BioContainers are
amd64-only, and emulation is slow and, for numerically heavy imaging code, sometimes wrong. Local
work is limited to writing code and `-stub` runs. Real execution happens on the cluster.
