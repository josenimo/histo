/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Unified MCMICRO-SOPA Pipeline Main Entrypoint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

nextflow.enable.dsl = 2

include { MCMICRO_OPTICAL } from './subworkflows/local/mcmicro_optical'
include { SOPA_SPATIAL    } from './subworkflows/local/sopa_spatial'

workflow {
    log.info """
    ===================================================================
    U N I F I E D   M C M I C R O - S O P A   P I P E L I N E
    ===================================================================
    Master MCMICRO Flag     : ${params.use_mcmicro}
    Input Pre-stitched Image: ${params.input_image}
    Input Cycle Samplesheet : ${params.input_cycle}
    Marker Sheet            : ${params.marker_sheet}
    Output Directory        : ${params.outdir}
    Technology              : ${params.technology}
    Use Cellpose            : ${params.use_cellpose}
    Cellpose Channel        : ${params.cellpose_channels}
    Cellpose Diameter       : ${params.cellpose_diameter}
    ===================================================================
    """

    if (params.use_mcmicro) {
        // Mode A: Opt-In MCMICRO Optical Preprocessing
        ch_input_cycle = Channel.fromPath(params.input_cycle)
            .splitCsv(header: true)
            .map { row ->
                def dfp_val = (row.containsKey('dfp') && row.dfp) ? file(row.dfp) : []
                def ffp_val = (row.containsKey('ffp') && row.ffp) ? file(row.ffp) : []
                [ row.sample, file(row.image_tiles), dfp_val, ffp_val ]
            }
            .groupTuple()
            .map { sample_id, images, dfps, mfps ->
                [ [ id: sample_id ], images, dfps, mfps ]
            }

        ch_marker_sheet = file(params.marker_sheet)

        MCMICRO_OPTICAL( ch_input_cycle, ch_marker_sheet )
        ch_sopa_input = MCMICRO_OPTICAL.out.latest_image
    } else {
        // Mode B: Default SOPA Mode (Single pre-stitched OME-TIFF)
        def image_path = params.input_image ?: params.input
        if (!image_path) {
            error "ERROR: Please specify --input_image <file.ome.tif> for SOPA mode, or --use_mcmicro true --input_cycle <samplesheet.csv> for MCMICRO mode."
        }

        ch_sopa_input = Channel.fromPath(image_path)
            .map { file_obj ->
                def sample_name = params.sample_id ?: file_obj.name.replaceAll(/\.(ome\.tif|ome\.tiff|tif|tiff)$/, '')
                [ [ id: sample_name ], file_obj ]
            }
    }

    // Run SOPA Distributed Spatial Analysis
    SOPA_SPATIAL( ch_sopa_input )
}
