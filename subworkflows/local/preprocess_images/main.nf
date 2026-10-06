// Cycles in, one stitched OME-TIFF per sample (or per TMA core) out.
// Grouping and multiMap pattern adapted from nf-core/mcmicro workflows/mcmicro.nf.

include { BASICPY    } from '../../../modules/nf-core/basicpy/main'
include { ASHLAR     } from '../../../modules/nf-core/ashlar/main'
include { BACKSUB    } from '../../../modules/nf-core/backsub/main'
include { COREOGRAPH } from '../../../modules/nf-core/coreograph/main'

workflow PREPROCESS_IMAGES {
    take:
    ch_cycles // channel: [ val(meta), path(image_tiles), path(dfp), path(ffp) ]
    ch_markersheet // channel: [ val(meta), path(csv) ] one marker sheet per sample, or empty

    main:

    // Illumination correction: supplied dfp/ffp are used, otherwise BaSiCPy computes them.
    // validateIlluminationColumns guarantees all-or-nothing per sample.
    ch_cycles
        .branch { _meta, _image_tiles, dfp, ffp ->
            supplied: dfp && ffp
            compute: true
        }
        .set { ch_illumination }

    BASICPY(ch_illumination.compute.map { meta, image_tiles, _dfp, _ffp -> [meta, image_tiles] })

    // meta carries cycle_number, so join() attaches each cycle's own profiles.
    ch_computed = ch_illumination.compute
        .map { meta, image_tiles, _dfp, _ffp -> [meta, image_tiles] }
        .join(BASICPY.out.profiles)

    ch_corrected = ch_computed.mix(ch_illumination.supplied)

    // Stitching. The cycle_number sort keeps images and profiles in matching order for Ashlar.
    ch_corrected
        .map { meta, image_tiles, dfp, ffp ->
            [meta.subMap('id'), [meta.cycle_number, image_tiles, dfp, ffp]]
        }
        .groupTuple(sort: { a, b -> a[0] <=> b[0] })
        .map { meta, cycles -> [meta] + cycles.collect { it[1..-1] }.transpose() }
        // flatten() turns a list of empty lists into [], which Ashlar reads as "no profiles".
        .multiMap { meta, images, dfps, ffps ->
            images: [meta, images]
            dfps: dfps.flatten()
            ffps: ffps.flatten()
        }
        .set { ch_ashlar }

    ASHLAR(ch_ashlar.images, ch_ashlar.dfps, ch_ashlar.ffps)

    // TMA dearray: one slide becomes N cores, each continuing as its own sample.
    // Runs before backsub so the unsubtracted image QC compares against is per core too.
    if (params.use_tma_dearray) {
        COREOGRAPH(ASHLAR.out.tif)

        // Core id comes from the patched module's {slide}_core001 filename; strip both
        // .tif and .ome.tif (Coreograph 2.4.6), or ".ome" leaks into ids and zarr names.
        ch_dearrayed = COREOGRAPH.out.cores
            .transpose()
            .map { meta, core ->
                def core_id = core.name.replaceFirst(/(?i)\.(ome\.)?tiff?$/, '')
                // error(), not assert: asserts inside channel operators are swallowed.
                if (!(core_id ==~ /.+_core\d{3}/)) {
                    error(
                        "Core filename ${core.name} does not match the expected {slide}_core000 " +
                        "pattern. The Coreograph module patch performs that rename; if the patch " +
                        "was lost during an `nf-core modules update`, this is what it looks like."
                    )
                }
                [meta + [id: core_id, slide: meta.id], core]
            }

        // Each core inherits its slide's sheet, re-keyed to core meta. combine(by: 0), not
        // join(), since join keeps only the first core per slide.
        ch_dearrayed_markers = ch_dearrayed
            .map { meta, _core -> [[id: meta.slide], meta] }
            .combine(ch_markersheet.map { meta, sheet -> [meta.subMap('id'), sheet] }, by: 0)
            .map { _slide, core_meta, sheet -> [core_meta, sheet] }
    }
    else {
        ch_dearrayed = ASHLAR.out.tif
        ch_dearrayed_markers = ch_markersheet
    }

    // Background subtraction. The sheet is passed as written; backsub keeps unknown columns.
    if (params.use_backsub) {
        ch_dearrayed
            .join(ch_dearrayed_markers)
            .multiMap { meta, image, markers ->
                image: [meta, image]
                markers: [meta, markers]
            }
            .set { ch_backsub }

        BACKSUB(ch_backsub.image, ch_backsub.markers)
        ch_images = BACKSUB.out.backsub_tif

        // backsub drops removed channels and renumbers the rest, so downstream must use its sheet.
        ch_effective_markers = BACKSUB.out.markerout
    }
    else {
        ch_images = ch_dearrayed
        ch_effective_markers = ch_dearrayed_markers
    }

    // Versions go to the `versions` topic and are collected in workflows/histo.nf.

    // Pre-subtraction image for QC, keyed like the images QC reads. Empty without backsub.
    ch_unsubtracted = params.use_backsub
        ? ch_dearrayed
        : channel.empty()

    emit:
    images       = ch_images          // channel: [ val(meta), path(image) ] one per sample, or one per TMA core
    markers      = ch_effective_markers  // channel: [ val(meta), path(csv) ] the channels each image actually has
    unsubtracted = ch_unsubtracted    // channel: [ val(meta), path(tif) ] Ashlar's output, pre-subtraction
}
