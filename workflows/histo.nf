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
include { REPORT                  } from '../modules/local/report'
include { FLUO_ANNOTATION         } from '../modules/local/fluo_annotation'
include { CELLPOSE                } from '../subworkflows/local/cellpose'
include { STARDIST                } from '../subworkflows/local/stardist'


include { argsCLI        } from '../modules/local/utils'
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow HISTO {
    take:
    ch_samplesheet // channel: samplesheet read in from --input
    ch_markersheet // channel: marker sheet read in from --marker_sheet
    outdir

    main:

    def ch_versions = channel.empty()

    if (params.use_preprocessing) {
        PREPROCESS_IMAGES(ch_samplesheet, ch_markersheet)

        // Grouping cycles into samples reduces meta to {id}, but the downstream
        // half needs sample and sdata_dir. They are per-sample and only
        // meaningful once cycles are stitched, so they are added here rather
        // than during samplesheet validation.
        ch_input_spatialdata = PREPROCESS_IMAGES.out.images.map { meta, image ->
            def m = meta + [
                sample: meta.id,
                sdata_dir: "${meta.id}.zarr",
            ]
            [m, image, []]
        }
    }
    else {
        ch_input_spatialdata = ch_samplesheet.map { meta -> [meta, meta.data_dir, []] }
    }

    (ch_spatialdata, versions) = TO_SPATIALDATA(ch_input_spatialdata)
    ch_versions = ch_versions.mix(versions)

    if (params.use_tissue_segmentation) {
        (ch_tissue_seg, versions) = TISSUE_SEGMENTATION(ch_spatialdata, argsCLI("tissue_segmentation"))
        ch_versions = ch_versions.mix(versions)
    }
    else {
        ch_tissue_seg = ch_spatialdata
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

    REPORT(ch_preprocessed)
    ch_versions = ch_versions.mix(REPORT.out.versions)

    // TMA cores are merged only at the very end, once every core has been
    // through every step on its own. Merging earlier would mean segmenting and
    // aggregating one large sparse object instead of many small dense ones,
    // which scales badly and loses the per-core QC report.
    //
    // This chains off REPORT rather than off ch_preprocessed. Both would give
    // the same cores, but REPORT mutates the zarr in place (it removes
    // .sopa_cache), so reading the same store concurrently would be a race.
    if (params.use_tma_dearray) {
        ch_cores_by_slide = REPORT.out.sdata
            .map { meta, sdata -> [[id: meta.slide], sdata] }
            .groupTuple()

        MERGE_SPATIALDATA(ch_cores_by_slide)
        ch_versions = ch_versions.mix(MERGE_SPATIALDATA.out.versions)
    }

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
