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

include { BASICPY } from '../../../modules/nf-core/basicpy/main'
include { ASHLAR  } from '../../../modules/nf-core/ashlar/main'

workflow PREPROCESS_IMAGES {
    take:
    ch_cycles // channel: [ val(meta), path(image_tiles), path(dfp), path(ffp) ]

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

    // Versions are emitted on the `versions` topic by all four mcmicro modules,
    // and collected in workflows/histo.nf. Nothing to mix here.

    emit:
    ome_tif = ASHLAR.out.tif // channel: [ val(meta), path(ome_tif) ]
}
