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
include { EXPLORER                } from '../modules/local/explorer'
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
    outdir

    main:

    def ch_versions = channel.empty()

    if (params.use_preprocessing) {
        PREPROCESS_IMAGES(ch_samplesheet)

        // Grouping cycles into samples reduces meta to {id}, but the downstream
        // half needs sample, sdata_dir and explorer_dir. They are per-sample and
        // only meaningful once cycles are stitched, so they are added here rather
        // than during samplesheet validation.
        ch_input_spatialdata = PREPROCESS_IMAGES.out.ome_tif.map { meta, ome_tif ->
            def m = meta + [
                sample: meta.id,
                sdata_dir: "${meta.id}.zarr",
                explorer_dir: "${meta.id}.explorer",
            ]
            [m, ome_tif, []]
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

    EXPLORER(ch_preprocessed, argsCLI("explorer"))

    REPORT(ch_preprocessed)

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
