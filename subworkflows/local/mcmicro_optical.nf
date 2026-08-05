/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    MCMICRO Optical Preprocessing Subworkflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

process BASICPY {
    tag "$meta.id"
    label 'process_medium'
    publishDir "${params.outdir}/illumination/basicpy", mode: 'copy'

    container 'docker.io/labsyspharm/basicpy-docker-mcmicro:1.2.0-patch5'

    input:
    tuple val(meta), path(raw_images)

    output:
    tuple val(meta), path(raw_images), path("*-dfp.ome.tif"), path("*-ffp.ome.tif"), emit: cycle_profiles

    script:
    def image_list = raw_images instanceof List ? raw_images : [raw_images]
    def commands = image_list.collect { img ->
        def base = img.name.replaceAll(/\.(ome\.tif|ome\.tiff|tif|tiff)$/, '')
        """
        python3 /opt/main.py -i $img -o . --output-flatfield $base --output-darkfield $base
        python3 -c "import tifffile; [tifffile.imwrite(f, tifffile.imread(f), photometric='minisblack') for f in ['${base}-dfp.ome.tif', '${base}-ffp.ome.tif']]"
        """
    }.join('\n')
    """
    export HOME=\$PWD
    export MPLCONFIGDIR=\$PWD
    $commands
    """

    stub:
    def image_list = raw_images instanceof List ? raw_images : [raw_images]
    def commands = image_list.collect { img ->
        def base = img.name.replaceAll(/\.(ome\.tif|ome\.tiff|tif|tiff)$/, '')
        "touch ${base}-dfp.ome.tif ${base}-ffp.ome.tif"
    }.join('\n')
    """
    $commands
    """
}

process ASHLAR {
    tag "$meta.id"
    label 'process_medium'
    publishDir "${params.outdir}/registration/ashlar", mode: 'copy'

    container "josenimo/jose_ashlar:1.21.0"

    input:
    tuple val(meta), path(raw_images), val(dfp), val(ffp)
    path marker_sheet

    output:
    tuple val(meta), path("*.ome.tif"), emit: ome_tiff

    script:
    def args = params.ashlar_args != null ? params.ashlar_args : '--maximum-shift 30'
    def prefix = "${meta.id}"
    def dfp_files = (dfp && dfp != []) ? (dfp instanceof List ? dfp.join(' ') : dfp.toString()) : ''
    def ffp_files = (ffp && ffp != []) ? (ffp instanceof List ? ffp.join(' ') : ffp.toString()) : ''
    def dfp_args = dfp_files ? "--dfp $dfp_files" : ''
    def ffp_args = ffp_files ? "--ffp $ffp_files" : ''
    """
    ashlar ${raw_images.join(' ')} $dfp_args $ffp_args -o ${prefix}.ome.tif $args
    """

    stub:
    def prefix = "${meta.id}"
    """
    touch ${prefix}.ome.tif
    """
}

process BACKSUB {
    tag "$meta.id"
    label 'process_medium'
    publishDir "${params.outdir}/backsub", mode: 'copy'

    container 'ghcr.io/schapirolabor/background_subtraction:v0.5.1'

    input:
    tuple val(meta), path(image)
    path marker_sheet

    output:
    tuple val(meta), path("*.ome.tif"), emit: ome_tiff

    script:
    def args = params.backsub_args != null ? params.backsub_args : ''
    def prefix = "${meta.id}_backsub"
    """
    export HOME=\$PWD
    export MPLCONFIGDIR=\$PWD

    backsub \
        -r $image \
        -m $marker_sheet \
        -o ${prefix}.ome.tif \
        -mo ${prefix}_markers.csv \
        $args
    """

    stub:
    def prefix = "${meta.id}_backsub"
    """
    touch ${prefix}.ome.tif
    """
}

process COREOGRAPH {
    tag "$meta.id"
    label 'process_high'
    publishDir "${params.outdir}/coreograph", mode: 'copy'

    container 'docker.io/labsyspharm/unetcoreograph:2.4.6'
    containerOptions '--platform linux/amd64'

    input:
    tuple val(meta), path(image)

    output:
    tuple val(meta), path("tma_cores/*[0-9]*.tif"), emit: cores

    script:
    def args = params.coreograph_args ?: '--channel 0 --downsampleFactor 3 --buffer 2'
    """
    export HOME=\$PWD
    export MPLCONFIGDIR=\$PWD
    mkdir -p tma_cores

    python3 $projectDir/bin/run_coreograph.py $image tma_cores
    python3 $projectDir/bin/fix_core_ome_tiff.py tma_cores $image
    """

    stub:
    """
    mkdir -p tma_cores
    python3 -c "import tifffile, numpy as np; [tifffile.imwrite(f'tma_cores/{i}.tif', np.ones((5, 100, 100), dtype=np.uint16), imagej=True) for i in range(1, 5)]"
    """
}

workflow MCMICRO_OPTICAL {
    take:
    ch_input_cycle  // channel: [ meta, raw_images, dfp, ffp ]
    ch_marker_sheet // channel: marker_sheet

    main:
    ch_ashlar_input = ch_input_cycle

    // 1. Conditional BaSiC Illumination Correction (Default true when use_mcmicro = true)
    if (params.use_basicpy) {
        ch_basicpy_input = ch_input_cycle.map { meta, raw_images, dfp, ffp -> [ meta, raw_images ] }
        BASICPY( ch_basicpy_input )
        ch_ashlar_input = BASICPY.out.cycle_profiles
    }

    // 2. Run Ashlar stitching & multi-cycle registration
    ASHLAR( ch_ashlar_input, ch_marker_sheet )
    ch_current_image = ASHLAR.out.ome_tiff

    // 3. Conditional Background Subtraction (Opt-In)
    if (params.use_backsub) {
        BACKSUB( ch_current_image, ch_marker_sheet )
        ch_current_image = BACKSUB.out.ome_tiff
    }

    // 4. Conditional TMA Dearraying (Coreograph - Opt-In)
    if (params.use_tma_dearray) {
        COREOGRAPH( ch_current_image )
        ch_current_image = COREOGRAPH.out.cores.flatMap { meta, core_files ->
            def sample_id = meta.id
            core_files.collect { f ->
                def core_id = f.name.replaceAll(/\.(tif|tiff)$/, '')
                [ [ id: "${sample_id}_core_${core_id}", sample: sample_id, core: core_id ], f ]
            }
        }
    }

    emit:
    latest_image = ch_current_image // channel: [ meta, ome_tiff ]
}
