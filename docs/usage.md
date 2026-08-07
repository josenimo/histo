# josenimo/histo: Usage

## Quick start

```bash
nextflow run josenimo/histo -r dev \
    -profile singularity,size_small,slurm \
    -params-file params.yml
```

Always give three profiles: a container engine, a size, and an executor.

Parameters go in `-params-file`, never in `-c`. Custom config files can set anything **except**
parameters.

## Inputs

Two files: a samplesheet and a marker sheet.

**Samplesheet**, one row per acquisition cycle:

```csv
sample,cycle_number,image_tiles
mysample,1,/abs/path/cycle01.ome.tiff
mysample,2,/abs/path/cycle02.ome.tiff
```

Optional `dfp` and `ffp` columns supply pre-computed illumination profiles. If you give them for one
cycle you must give them for all; otherwise BaSiCPy computes them.

**Marker sheet**, one row per channel, `channel_number` running 1..N without gaps:

```csv
channel_number,cycle_number,marker_name,filter
1,1,DNA_1,DAPI
2,1,CD45,FITC
```

`--use_backsub` additionally needs `exposure` and `background` columns.

Paths must be absolute.

## Parameters

Only `input`, `outdir` and a segmentation backend are required. Everything below has a default.

| Parameter                     | Default              | Change it when                                                                                         |
| ----------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------ |
| `use_preprocessing`           | `true`               | Your image is already stitched. Then the samplesheet is one row per sample with a `data_path` column.  |
| `marker_sheet`                | none                 | Required when `use_preprocessing` is true.                                                             |
| `ashlar_args`                 | `--maximum-shift 30` | Stitching misaligns.                                                                                   |
| `use_backsub`                 | `false`              | You have background channels to subtract.                                                              |
| `use_tma_dearray`             | `false`              | Your slide is a tissue microarray. Each core is then processed alone and the results merged per slide. |
| `use_cellpose`                | `false`              | Exactly one of `use_cellpose` or `use_stardist` must be true.                                          |
| `cellpose_channels`           | none                 | Always. Use a marker name, e.g. `"DNA_1"`.                                                             |
| `cellpose_diameter`           | none                 | Cells are not ~30 px across.                                                                           |
| `patch_width_pixel`           | none                 | Always. See below.                                                                                     |
| `patch_overlap_pixel`         | none                 | Set to roughly twice a cell diameter.                                                                  |
| `use_tissue_segmentation`     | `false`              | Large empty areas you want skipped.                                                                    |
| `use_fluorescence_annotation` | `false`              | You want marker-based cell typing.                                                                     |
| `aggregate_channels`          | none                 | Set `true` to get per-cell channel intensities.                                                        |

Full list with descriptions: `nextflow run josenimo/histo -r dev --help`.

### Choosing `patch_width_pixel`

This decides whether segmentation parallelises, and it is not automatic. Aim for **16 to 200
patches**: `patch_width_pixel = sqrt(width * height / target_patches)`.

| Stitched image | 2000 | 5000 | 8000 | 10000 |
| -------------- | ---- | ---- | ---- | ----- |
| 3k × 3k        | 4    | 1    | 1    | 1     |
| 25k × 25k      | 169  | 25   | 16   | 9     |
| 50k × 50k      | 625  | 100  | 49   | 25    |
| 115k × 115k    | 3364 | 529  | 225  | 144   |

One patch means no parallelism at all. Thousands means the scheduler costs more than the work.
Memory is not the constraint — a 5000 px patch is about 50 MB.

Get the dimensions with `scratch/inspect-ome.py stitched.ome.tif`.

## Profiles

**Size** — pick by stitched image size. Only `size_tiny` is derived from measurement; the rest are
estimates and will change.

| Profile       | For                    |
| ------------- | ---------------------- |
| `size_tiny`   | under ~1 GB, test data |
| `size_small`  | up to ~10 GB           |
| `size_medium` | ~10–40 GB              |
| `size_huge`   | ~40 GB and up          |

**Executor** — `slurm`, or omit for local execution. Without it every task runs on the machine you
launched from.

**Containers** — `singularity` on the cluster. Images must be pre-staged; see
[containers.md](containers.md).

## Example

```yaml
input: /abs/path/samplesheet.csv
marker_sheet: /abs/path/markers.csv
outdir: /abs/path/results

use_preprocessing: true
technology: ome_tif

use_cellpose: true
cellpose_channels: "DNA_1"
cellpose_diameter: 35
patch_width_pixel: 1500
patch_overlap_pixel: 50

aggregate_channels: true
```

## Running on the cluster

Launch from a directory that is **not** the pipeline clone, so run artifacts do not land in the
source tree. Nextflow submits the SLURM jobs itself; you never write an sbatch script. Run it inside
`tmux` so it outlives your session.

```bash
mkdir -p ~/runs/myrun && cd ~/runs/myrun

# Keep temporary files off the shared /tmp, which is small and communal. Without
# this a run dies with "No space left on device" on a path under /tmp, which looks
# like a disk-quota problem and is not one.
export TMPDIR=/fast/AG_Coscia/$USER/tmp
export NXF_TEMP="$TMPDIR"
export NXF_OPTS="-Djava.io.tmpdir=$TMPDIR"
mkdir -p "$TMPDIR"

# Stops a launch-time fetch of a config this pipeline does not use.
export NXF_OFFLINE=true

nextflow run /path/to/histo -profile singularity,size_small,slurm -params-file params.yml -resume
```

All three temp variables are needed for different consumers: `TMPDIR` for tools inside
containers, `NXF_TEMP` for Nextflow's own scratch, and `java.io.tmpdir` for the JVM,
which is the one that fails first and least helpfully.

Validate before submitting — this catches bad paths and parameter types in seconds rather than after
a queue wait:

```bash
nextflow run /path/to/histo -profile laptop -stub -params-file params.yml
```
