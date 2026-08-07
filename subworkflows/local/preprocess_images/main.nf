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

        // The sheet that describes what the image now contains. backsub can drop
        // background channels, so its rewritten markerout is the truthful one and
        // the input sheet would name channels that no longer exist.
        ch_effective_markers = BACKSUB.out.markerout.map { _meta, markers -> markers }.first()
    }
    else {
        ch_registered = ASHLAR.out.tif

        // No backsub, so the input sheet still describes the image. Written out as a
        // file rather than passed as rows, so that whatever consumes it downstream
        // takes the same shape in both branches.
        ch_effective_markers = ch_markersheet
            .map { rows ->
                [
                    'channel_number,marker_name',
                    rows.sort { a, b -> (a.channel_number as int) <=> (b.channel_number as int) }
                        .collect { r -> "${r.channel_number},${r.marker_name}" },
                ]
            }
            .flatten()
            .collectFile(name: 'markers_effective.csv', sort: false, newLine: true)
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
        //
        // The extension strip must handle both `.tif` (Coreograph 2.2.9) and
        // `.ome.tif` (2.4.6). Matching only /\.tif$/ leaves a trailing ".ome" in
        // the ID on 2.4.6, which is the version we run, and that ID goes on to
        // become the sdata directory name and the prefix of every merged element.
        ch_images = COREOGRAPH.out.cores
            .transpose()
            .map { meta, core ->
                def core_id = core.name.replaceFirst(/(?i)\.(ome\.)?tiff?$/, '')
                // error(), not assert: an assertion thrown inside a channel
                // operator closure is swallowed and the run carries on.
                if (!(core_id ==~ /.+_core\d{3}/)) {
                    error(
                        "Core filename ${core.name} does not match the expected {slide}_core000 " +
                        "pattern. The Coreograph module patch performs that rename; if the patch " +
                        "was lost during an `nf-core modules update`, this is what it looks like."
                    )
                }
                [meta + [id: core_id, slide: meta.id], core]
            }
    }
    else {
        ch_images = ch_registered
    }

    // Versions are emitted on the `versions` topic by all four mcmicro modules,
    // and collected in workflows/histo.nf. Nothing to mix here.

    emit:
    images  = ch_images             // channel: [ val(meta), path(image) ] one per sample, or one per TMA core
    markers = ch_effective_markers  // channel: path(csv) describing the channels the images actually have
}
