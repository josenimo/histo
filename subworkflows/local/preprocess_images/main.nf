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
    ch_markersheet // channel: [ val(meta), path(csv) ] one marker sheet per sample, or empty

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
    // TMA dearray. Optional, off by default.
    //
    // This is the one step that changes the cardinality of the pipeline: one slide
    // becomes N cores, and each core continues through the downstream half as an
    // independent sample with its own SpatialData object.
    //
    // Before background subtraction, deliberately. The two orders produce the same
    // pixels -- backsub subtracts a scaled background channel per pixel and has no
    // whole-slide term, so subtracting then cutting and cutting then subtracting
    // agree -- but only this order leaves an unsubtracted image that is the same
    // shape as the thing QC reads. With backsub first, the pre-subtraction image is
    // a whole slide while the stores QC reads are single cores, so there is nothing
    // to compare a core against and the before-and-after check silently does not
    // happen on the TMA path. That is how a run with use_backsub = true produced a
    // report that showed no subtraction at all and said nothing about why.
    //
    // Coreograph is unaffected by the swap: it detects cores on --channel 0, the
    // nuclear stain, which has no background assigned and is therefore identical
    // before and after subtraction.
    //
    if (params.use_tma_dearray) {
        COREOGRAPH(ASHLAR.out.tif)

        // transpose() turns [meta, [core1, core2, ...]] into one item per core.
        // The core's identity comes from its filename, which the patched module
        // writes as {slide}_core001. meta.slide is retained so cores can be
        // grouped back to their slide later.
        //
        // The extension strip must handle both `.tif` (Coreograph 2.2.9) and
        // `.ome.tif` (2.4.6). Matching only /\.tif$/ leaves a trailing ".ome" in
        // the ID on 2.4.6, which is the version we run, and that ID goes on to
        // become the sdata directory name and the prefix of every merged element.
        ch_dearrayed = COREOGRAPH.out.cores
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

        // Each core inherits its slide's marker sheet. Dearraying cuts the image up
        // but does not change what was stained, so every core of a slide has the same
        // channels.
        //
        // combine(by: 0) rather than join(): join pairs one item per key and a slide
        // has many cores, so it would keep the first core and drop the rest. Re-keying
        // to the core rather than leaving this keyed by slide means every consumer
        // downstream joins on the same meta it already uses.
        ch_dearrayed_markers = ch_dearrayed
            .map { meta, _core -> [[id: meta.slide], meta] }
            .combine(ch_markersheet.map { meta, sheet -> [meta.subMap('id'), sheet] }, by: 0)
            .map { _slide, core_meta, sheet -> [core_meta, sheet] }
    }
    else {
        ch_dearrayed = ASHLAR.out.tif
        ch_dearrayed_markers = ch_markersheet
    }

    //
    // Background subtraction. Optional, off by default.
    //
    // One code path for both shapes. Whatever came out of the step above -- one
    // slide, or N cores each keyed by its own id -- is subtracted the same way, and
    // the fan-out that used to be needed to spread a slide-level marker sheet across
    // cores after subtraction is gone: the sheet is already per core by the time
    // backsub sees it.
    //
    // The sheet is passed through as the user wrote it. backsub reads it with
    // pd.read_csv and addresses columns by name, so columns it has no use for,
    // channel_role and channel_compartment among them, are carried through to its
    // marker output rather than rejected. nf-core/mcmicro rewrites the sheet to six
    // columns; that is not required, and rewriting it here is what previously forced
    // the sheet to be a single broadcast file rather than one per sample.
    //
    if (params.use_backsub) {
        // join() rather than combine(): each image brings its own sheet, so the two
        // are matched by key instead of one sheet being broadcast over every image.
        ch_dearrayed
            .join(ch_dearrayed_markers)
            .multiMap { meta, image, markers ->
                image: [meta, image]
                markers: [meta, markers]
            }
            .set { ch_backsub }

        BACKSUB(ch_backsub.image, ch_backsub.markers)
        ch_images = BACKSUB.out.backsub_tif

        // The sheet that describes what the image now contains, per sample or per
        // core.
        //
        // backsub writes a new sheet rather than echoing its input, and the
        // difference matters twice over: rows whose remove column is set are gone,
        // and channel_number is renumbered 1..N across what survives. So the input
        // sheet would both name channels the image no longer has and number the rest
        // wrongly, which is why this is the sheet everything downstream reads.
        ch_effective_markers = BACKSUB.out.markerout
    }
    else {
        ch_images = ch_dearrayed

        // No backsub, so the sheet from the samplesheet still describes the image
        // exactly, and it is passed through untouched. Every consumer parses the CSV
        // by column name and ignores what it does not need.
        ch_effective_markers = ch_dearrayed_markers
    }

    // Versions are emitted on the `versions` topic by all four mcmicro modules,
    // and collected in workflows/histo.nf. Nothing to mix here.

    // The image before background subtraction, for QC to compare against.
    //
    // Keyed exactly like the images QC reads, on both paths, because dearraying now
    // happens first: one entry per sample without a TMA, one per core with one.
    // Emitted only when backsub ran, since without it there is nothing to compare.
    // Empty rather than absent in that case, so the consumer takes the same shape
    // either way.
    ch_unsubtracted = params.use_backsub
        ? ch_dearrayed
        : channel.empty()

    emit:
    images       = ch_images          // channel: [ val(meta), path(image) ] one per sample, or one per TMA core
    markers      = ch_effective_markers  // channel: [ val(meta), path(csv) ] the channels each image actually has
    unsubtracted = ch_unsubtracted    // channel: [ val(meta), path(tif) ] Ashlar's output, pre-subtraction
}
