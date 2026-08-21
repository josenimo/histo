# josenimo/histo: Pipeline paths

The three routes through the pipeline that have been run on real data. Everything else in
`nextflow.config` is off by default, so these are the shapes a run actually takes.

![Metro map of the three pipeline paths](images/pipeline_paths.svg)

## The same thing as a table

Read down a column to get one run's process list, in order.

| Station                       |  mIF slide   | WSI, background subtracted | TMA, dearrayed |
| ----------------------------- | :----------: | :------------------------: | :------------: |
| `BASICPY`                     |      x       |             x              |       x        |
| `ASHLAR`                      |      x       |             x              |       x        |
| `BACKSUB`                     |              |             x              |    optional    |
| `COREOGRAPH`                  |              |                            |       x        |
| `TO_SPATIALDATA`              |      x       |             x              |       x        |
| `SET_CHANNEL_NAMES`           |      x       |             x              |       x        |
| `MAKE_IMAGE_PATCHES`          |      x       |             x              |       x        |
| `PATCH_SEGMENTATION_CELLPOSE` | x, per patch |        x, per patch        |  x, per patch  |
| `RESOLVE_CELLPOSE`            |      x       |             x              |       x        |
| `AGGREGATE`                   |      x       |             x              |       x        |
| `PUBLISH_SPATIALDATA`         |      x       |             x              |       x        |
| `QC_METRICS`                  |      x       |             x              |       x        |
| `QC_IMAGES`                   |      x       |             x              |       x        |
| `QC_REPORT`                   |      x       |             x              |       x        |
| `MERGE_SPATIALDATA`           |              |                            |       x        |

Everything from `COREOGRAPH` onward runs once per core on the TMA path, and
`MERGE_SPATIALDATA` puts the cores of one slide back together at the end. It runs in parallel
with `PUBLISH_SPATIALDATA` rather than after it: both read the finished store, neither writes
to it.

## What the map does not show

- `TISSUE_SEGMENTATION` and `FLUO_ANNOTATION` are off in all three runs. Both sit between
  `MAKE_IMAGE_PATCHES` and `AGGREGATE`.
- `use_preprocessing = false` is a fourth entry point, for images arriving pre-stitched. It
  starts at `TO_SPATIALDATA` and skips `SET_CHANNEL_NAMES`, because such an image is assumed to
  carry its own channel names.
- Supplying illumination profiles in the samplesheet bypasses `BASICPY`.
- StarDist substitutes `PATCH_SEGMENTATION_STARDIST` and `RESOLVE_STARDIST` for the two Cellpose
  stations.

The pre-subtraction image reaching `QC_METRICS` is a second input rather than part of the flow,
which is why it is dashed. It exists only when `use_backsub` is set and `use_tma_dearray` is not:
a dearrayed core has no whole-slide before-image to compare against.
