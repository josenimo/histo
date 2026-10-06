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
sample,cycle_number,image_tiles,marker_sheet
mysample,1,/abs/path/cycle01.ome.tiff,/abs/path/markers_mysample.csv
mysample,2,/abs/path/cycle02.ome.tiff,/abs/path/markers_mysample.csv
othersample,1,/abs/path/other_cycle01.ome.tiff,/abs/path/markers_other.csv
```

`marker_sheet` is required and names the sheet for that sample. It repeats on every cycle row of a
sample and every copy must be the same file, because the sheet describes the whole stitched image
rather than one cycle of it. Two samples may name different sheets, which is the reason this is a
column rather than a parameter: one run can carry samples with different channel layouts.

Optional `dfp` and `ffp` columns supply pre-computed illumination profiles. If you give them for one
cycle you must give them for all; otherwise BaSiCPy computes them.

**Marker sheet**, one row per channel, `channel_number` running 1..N without gaps:

```csv
channel_number,cycle_number,marker_name,channel_role,channel_compartment,filter
1,1,DNA_1,dna,nuclear,DAPI
2,1,CD45,marker,membrane,FITC
```

`channel_role` is required and states what the pipeline should do with the channel:

| Role               | Meaning                                                                                                                           |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `dna`              | A nuclear stain. Every cycle needs at least one: registration, segmentation and the cross-cycle photobleaching check all read it. |
| `marker`           | A biological readout.                                                                                                             |
| `autofluorescence` | Acquired in order to be subtracted rather than interpreted. This is what `background` must point at.                              |
| `blank`            | Expected to be dark. QC checks that it is, rather than reporting it as a result.                                                  |

Giving the role explicitly is what stops the pipeline guessing which channel is a nuclear stain by
matching its name, which works until someone stains with Hoechst.

`channel_compartment` is optional and states where the signal belongs: `nuclear`, `cytoplasm`,
`membrane`, or a `+`-joined combination such as `nuclear+cytoplasm`. Order is not significant. QC
can only judge whether a marker landed where it should if the sheet says where that is, so leaving
it blank costs a check rather than breaking a run.

`--use_backsub` additionally needs `exposure` and `background` columns. `background` names the
`marker_name` of the channel to subtract, and that channel must itself have `channel_role` set to
`autofluorescence`. The two columns describe one fact, so they are checked against each other.

Paths must be absolute.

## Parameters

Only `input`, `outdir` and a segmentation backend are required. Everything below has a default.

**Booleans on the command line follow Nextflow's rule: a bare flag means true, and anything else
means use the default.** `--use_backsub` switches it on. To switch something off, leave it out, or
use a params file where `use_backsub: false` is a real boolean. Writing a value after the flag does
not work and never did: Nextflow reads the flag on its own, sets it true, and throws the value away
before the pipeline sees it, so `--use_backsub false` would perform background subtraction. The
pipeline stops at startup rather than letting that happen, for every boolean it declares.

| Parameter                     | Default              | Change it when                                                                                         |
| ----------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------ |
| `use_preprocessing`           | `true`               | Your image is already stitched. Then the samplesheet is one row per sample with a `data_path` column.  |
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
