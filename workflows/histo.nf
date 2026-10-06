/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    IMPORT MODULES / SUBWORKFLOWS / FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/
include { paramsSummaryMap        } from 'plugin/nf-schema'
include { softwareVersionsToYAML  } from '../subworkflows/nf-core/utils_nfcore_pipeline'
include { methodsDescriptionText  } from '../subworkflows/local/utils_nfcore_histo_pipeline'

include { PREPROCESS_IMAGES       } from '../subworkflows/local/preprocess_images'
include { TO_SPATIALDATA          } from '../modules/local/to_spatialdata'
include { MAKE_IMAGE_PATCHES      } from '../modules/local/make_image_patches'
include { TISSUE_SEGMENTATION     } from '../modules/local/tissue_segmentation'
include { AGGREGATE               } from '../modules/local/aggregate'
include { MERGE_SPATIALDATA       } from '../modules/local/merge_spatialdata'
include { MERGE_REPORT       } from '../modules/local/merge_report'
include { SET_CHANNEL_NAMES       } from '../modules/local/set_channel_names'
include { PUBLISH_SPATIALDATA     } from '../modules/local/publish_spatialdata'
include { FLUO_ANNOTATION         } from '../modules/local/fluo_annotation'
include { CELLPOSE                } from '../subworkflows/local/cellpose'
include { STARDIST                } from '../subworkflows/local/stardist'
include { QC                      } from '../subworkflows/local/qc'


include { argsCLI        } from '../modules/local/utils'
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

// Adds per-sample keys after stitching. Images and marker sheets must both use it, as they join on meta.
// Top-level def because Nextflow 26 does not resolve a local closure called inside a map closure.
def addSampleKeys(meta) {
    return meta + [
        sample: meta.id,
        sdata_dir: "${meta.id}.zarr",
    ]
}

workflow HISTO {
    take:
    ch_samplesheet // channel: samplesheet read in from --input
    ch_markersheet // channel: [ val(meta), path(csv) ] one marker sheet per sample
    outdir

    main:

    def ch_versions = channel.empty()

    if (params.use_preprocessing) {
        PREPROCESS_IMAGES(ch_samplesheet, ch_markersheet)

        ch_input_spatialdata = PREPROCESS_IMAGES.out.images.map { meta, image ->
            [addSampleKeys(meta), image, []]
        }
        ch_markers = PREPROCESS_IMAGES.out.markers.map { meta, markers ->
            [addSampleKeys(meta), markers]
        }
    }
    else {
        ch_input_spatialdata = ch_samplesheet.map { meta -> [meta, meta.data_dir, []] }

        // Pre-stitched images are assumed to carry their own channel names.
        ch_markers = channel.empty()
    }

    (ch_spatialdata, versions) = TO_SPATIALDATA(ch_input_spatialdata)
    ch_versions = ch_versions.mix(versions)

    // Ashlar output has only Channel:0:N names; rename from the marker sheet. Must precede
    // AGGREGATE (feature column names) and segmentation (cellpose_channels by marker name).
    if (params.use_preprocessing) {
        SET_CHANNEL_NAMES(ch_spatialdata.join(ch_markers))
        ch_named = SET_CHANNEL_NAMES.out.sdata
        ch_versions = ch_versions.mix(SET_CHANNEL_NAMES.out.versions)
    }
    else {
        ch_named = ch_spatialdata
    }

    if (params.use_tissue_segmentation) {
        (ch_tissue_seg, versions) = TISSUE_SEGMENTATION(ch_named, argsCLI("tissue_segmentation"))
        ch_versions = ch_versions.mix(versions)
    }
    else {
        ch_tissue_seg = ch_named
    }

    if (params.use_cellpose) {
        (ch_image_patches, versions) = MAKE_IMAGE_PATCHES(ch_tissue_seg, argsCLI("image_patches"))
        ch_versions = ch_versions.mix(versions)

        (ch_resolved, versions) = CELLPOSE(ch_image_patches)
        ch_versions = ch_versions.mix(versions)
    }

    if (params.use_stardist) {
        (ch_image_patches, versions) = MAKE_IMAGE_PATCHES(ch_tissue_seg, argsCLI("image_patches"))
        ch_versions = ch_versions.mix(versions)

        (ch_resolved, versions) = STARDIST(ch_image_patches)
        ch_versions = ch_versions.mix(versions)
    }

    (ch_aggregated, versions) = AGGREGATE(ch_resolved, argsCLI("aggregate"))
    ch_versions = ch_versions.mix(versions)

    if (params.use_fluorescence_annotation) {
        (ch_annotated, versions) = FLUO_ANNOTATION(ch_aggregated, argsCLI("fluorescence_annotation"))
        ch_versions = ch_versions.mix(versions)
    }
    else {
        ch_annotated = ch_aggregated
    }

    ch_preprocessed = ch_annotated

    // QC needs the aggregated intensity matrix. Nothing writes to the store after this point,
    // so QC and the merge can read it concurrently.
    if (params.use_qc) {
        def ch_unsubtracted = params.use_preprocessing
            ? PREPROCESS_IMAGES.out.unsubtracted
            : channel.empty()

        QC(ch_preprocessed, ch_markers, ch_unsubtracted)
        ch_versions = ch_versions.mix(QC.out.versions)
    }

    // TMA cores are merged last so each core is segmented and QCed on its own.
    // `sample` is set because downstream processes tag on meta.sample.
    if (params.use_tma_dearray) {
        ch_cores_by_slide = ch_preprocessed
            .map { meta, sdata -> [[id: meta.slide, sample: meta.slide], sdata] }
            .groupTuple()

        MERGE_SPATIALDATA(ch_cores_by_slide)
        ch_versions = ch_versions.mix(MERGE_SPATIALDATA.out.versions)

        // Only the merged store is published; it already contains every core's elements.
        ch_publish = MERGE_SPATIALDATA.out.merged

        // One slide-level QC page from the per-core metrics, grouped on the same key as the merge.
        if (params.use_qc) {
            ch_slide_metrics = QC.out.metrics
                .map { meta, metrics -> [[id: meta.slide, sample: meta.slide], metrics] }
                .groupTuple()

            MERGE_REPORT(ch_slide_metrics)
            ch_versions = ch_versions.mix(MERGE_REPORT.out.versions)
        }
    }
    else {
        ch_publish = ch_preprocessed
    }

    PUBLISH_SPATIALDATA(ch_publish)

    //
    // Collate and save software versions
    //
    def topic_versions = channel.topic("versions")
        .distinct()
        .branch { entry ->
            versions_file: entry instanceof Path
            versions_tuple: true
        }

    def topic_versions_string = topic_versions.versions_tuple
        .map { process, tool, version ->
            [ process[process.lastIndexOf(':')+1..-1], "  ${tool}: ${version}" ]
        }
        .groupTuple(by:0)
        .map { process, tool_versions ->
            tool_versions.unique().sort()
            "${process}:\n${tool_versions.join('\n')}"
        }

    def ch_collated_versions = softwareVersionsToYAML(ch_versions.mix(topic_versions.versions_file))
        .mix(topic_versions_string)
        .collectFile(
            storeDir: "${outdir}/pipeline_info",
            name: 'histo_software_versions.yml',
            sort: true,
            newLine: true
        )
    emit:
    versions       = ch_versions                 // channel: [ path(versions.yml) ]
}
