//
// Preprocessing: illumination correction, then stitching and registration.
//
// Takes one row per acquisition cycle and produces one stitched OME-TIFF per
// sample. That OME-TIFF is the handoff boundary to the downstream half.
//
// Adapted from nf-core/mcmicro's workflows/mcmicro.nf. The grouping and
// multiMap pattern below is theirs; it is subtle and it works, so it is copied
// rather than reinvented.
//

include { BASICPY    } from '../../../modules/nf-core/basicpy/main'
include { ASHLAR     } from '../../../modules/nf-core/ashlar/main'
include { BACKSUB    } from '../../../modules/nf-core/backsub/main'
include { COREOGRAPH } from '../../../modules/nf-core/coreograph/main'

workflow PREPROCESS_IMAGES {
    take:
    ch_cycles // channel: [ val(meta), path(image_tiles), path(dfp), path(ffp) ]
    ch_markersheet // channel: list of marker rows, or empty

    main:

    //
    // Illumination correction.
    //
    // Which path a sample takes is decided by the samplesheet, not by a
    // parameter: supplying dfp and ffp means "use these", omitting them means
    // "compute them". The input already states the intent, so a parameter would
    // be a second place to say the same thing and a second place to disagree.
    //
    // validateParams enforces that dfp and ffp are all-or-nothing per sample, so
    // a half-populated column cannot silently misalign profiles against cycles.
    //
    ch_cycles
        .branch { _meta, _image_tiles, dfp, ffp ->
            supplied: dfp && ffp
            compute: true
        }
        .set { ch_illumination }

    BASICPY(ch_illumination.compute.map { meta, image_tiles, _dfp, _ffp -> [meta, image_tiles] })

    // join() matches on meta, which carries cycle_number, so each cycle's
    // profiles attach to the cycle they were computed from.
    ch_computed = ch_illumination.compute
        .map { meta, image_tiles, _dfp, _ffp -> [meta, image_tiles] }
        .join(BASICPY.out.profiles)

    ch_corrected = ch_computed.mix(ch_illumination.supplied)

    //
    // Stitching and registration.
    //
    // Group cycles back into samples and order them. The sort on cycle_number is
    // what guarantees Ashlar receives images and illumination profiles in
    // matching order; without it they can be silently misaligned.
    //
    ch_corrected
        .map { meta, image_tiles, dfp, ffp ->
            [meta.subMap('id'), [meta.cycle_number, image_tiles, dfp, ffp]]
        }
        .groupTuple(sort: { a, b -> a[0] <=> b[0] })
        .map { meta, cycles -> [meta] + cycles.collect { it[1..-1] }.transpose() }
        // flatten() collapses a list of empty lists into a single empty list,
        // which is how Ashlar receives "no illumination profiles".
        .multiMap { meta, images, dfps, ffps ->
            images: [meta, images]
            dfps: dfps.flatten()
            ffps: ffps.flatten()
        }
        .set { ch_ashlar }

    ASHLAR(ch_ashlar.images, ch_ashlar.dfps, ch_ashlar.ffps)

    //
    // Background subtraction. Optional, off by default.
    //
    // backsub wants a marker file with exactly the six columns it reads, so the
    // sheet is rewritten rather than passed through: nulls become empty strings,
    // and the extra columns are dropped. Same approach as nf-core/mcmicro.
    //
    if (params.use_backsub) {
        ch_backsub_markers = ch_markersheet
            .map { rows ->
                [
                    'channel_number,cycle_number,marker_name,exposure,background,remove',
                    rows.collect { r ->
                        [r.channel_number, r.cycle_number, r.marker_name, r.exposure, r.background, r.remove].join(',')
                    },
                ]
            }
            .flatten()
            .map { it.replaceAll('(?<=,|^)null(?=,|$)', '') }
            .collectFile(name: 'markers_backsub.csv', sort: false, newLine: true)

        // combine() rather than join(): one marker sheet serves every sample, so
        // it is broadcast against the images rather than matched by key.
        ASHLAR.out.tif
            .combine(ch_backsub_markers)
            .multiMap { meta, image, markers ->
                image: [meta, image]
                markers: [meta, markers]
            }
            .set { ch_backsub }

        BACKSUB(ch_backsub.image, ch_backsub.markers)
        ch_registered = BACKSUB.out.backsub_tif
    }
    else {
        ch_registered = ASHLAR.out.tif
    }

    //
    // TMA dearray. Optional, off by default.
    //
    // This is the one step that changes the cardinality of the pipeline: one slide
    // becomes N cores, and each core continues through the downstream half as an
    // independent sample with its own SpatialData object.
    //
    if (params.use_tma_dearray) {
        COREOGRAPH(ch_registered)

        // transpose() turns [meta, [core1, core2, ...]] into one item per core.
        // The core's identity comes from its filename, which the patched module
        // writes as {slide}_core001. meta.slide is retained so cores can be
        // grouped back to their slide later.
        ch_images = COREOGRAPH.out.cores
            .transpose()
            .map { meta, core ->
                [meta + [id: core.name.replaceFirst(/\.tif$/, ''), slide: meta.id], core]
            }
    }
    else {
        ch_images = ch_registered
    }

    // Versions are emitted on the `versions` topic by all four mcmicro modules,
    // and collected in workflows/histo.nf. Nothing to mix here.

    emit:
    images = ch_images // channel: [ val(meta), path(image) ] one per sample, or one per TMA core
}
