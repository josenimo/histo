/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    SOPA Spatial Analysis Subworkflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

process TO_SPATIALDATA {
    tag "$meta.id"
    label 'process_medium'

    /* container "community.wave.seqera.io/library/python_sopa:54a97bc5a187152d" */
    container '/fast/AG_Coscia/software/singularity/python_sopa.sif'

    input:
    tuple val(meta), path(image)

    output:
    tuple val(meta), path("*.zarr"), emit: sdata

    script:
    def tech = params.technology ?: 'ome_tif'
    def prefix = "${meta.id}"
    """
    export HOME=\$PWD
    export NUMBA_CACHE_DIR=\$PWD
    export MPLCONFIGDIR=\$PWD

    python3 $projectDir/bin/convert_to_spatialdata.py ${prefix}.zarr $image '$tech'
    """

    stub:
    def prefix = "${meta.id}"
    """
    mkdir -p ${prefix}.zarr
    touch ${prefix}.zarr/.zgroup
    """
}

process MAKE_IMAGE_PATCHES {
    tag "$meta.id"
    label 'process_low'

   /* container "community.wave.seqera.io/library/python_sopa:54a97bc5a187152d" */
    container '/fast/AG_Coscia/software/singularity/python_sopa.sif'

    input:
    tuple val(meta), path(sdata)

    output:
    tuple val(meta), path(sdata), path("num_patches.txt"), emit: sdata_patches

    script:
    def width = params.patch_width_pixel ?: 1000
    def overlap = params.patch_overlap_pixel ?: 50
    """
    export HOME=\$PWD
    export NUMBA_CACHE_DIR=\$PWD
    export MPLCONFIGDIR=\$PWD

    sopa patchify image $sdata --patch-width-pixel $width --patch-overlap-pixel $overlap
    python3 -c "import spatialdata; sdata = spatialdata.read_zarr('$sdata'); print(len(sdata['image_patches']))" > num_patches.txt
    """

    stub:
    """
    mkdir -p $sdata
    echo "2" > num_patches.txt
    """
}

process PATCH_SEGMENTATION_CELLPOSE {
    tag "${meta.id}_patch_${patch_index}"
    label 'process_high'

    /* container "community.wave.seqera.io/library/python_sopa:54a97bc5a187152d" */
    container '/fast/AG_Coscia/software/singularity/python_sopa.sif'

    input:
    tuple val(meta), path(sdata), val(patch_index)

    output:
    tuple val(meta), path(sdata), path("${meta.id}_patch_${patch_index}.parquet"), emit: patch_parquet

    script:
    def channels = params.cellpose_channels ?: '0'
    def diameter = params.cellpose_diameter ?: 35
    """
    export HOME=\$PWD
    export NUMBA_CACHE_DIR=\$PWD
    export MPLCONFIGDIR=\$PWD
    mkdir -p ./cellpose_cache
    export CELLPOSE_LOCAL_MODELS_PATH=./cellpose_cache

    sopa segmentation cellpose $sdata --patch-index $patch_index --diameter $diameter --channels '$channels' --no-gpu --min-area 0

    mv $sdata/.sopa_cache/cellpose_boundaries/${patch_index}.parquet ${meta.id}_patch_${patch_index}.parquet
    """

    stub:
    """
    mkdir -p $sdata
    touch ${meta.id}_patch_${patch_index}.parquet
    """
}

process RESOLVE_CELLPOSE {
    tag "$meta.id"
    label 'process_medium'

    /* container "community.wave.seqera.io/library/python_sopa:54a97bc5a187152d" */
    container '/fast/AG_Coscia/software/singularity/python_sopa.sif'

    input:
    tuple val(meta), path(sdata), path(parquets)

    output:
    tuple val(meta), path(sdata), emit: sdata_resolved

    script:
    """
    export HOME=\$PWD
    export NUMBA_CACHE_DIR=\$PWD
    export MPLCONFIGDIR=\$PWD

    mkdir -p $sdata/.sopa_cache/cellpose_boundaries
    for f in $parquets; do
        idx=\$(echo \$f | sed -E 's/.*_patch_([0-9]+)\\.parquet/\\1/')
        cp \$f $sdata/.sopa_cache/cellpose_boundaries/\${idx}.parquet
    done

    sopa resolve cellpose $sdata
    """

    stub:
    """
    mkdir -p $sdata
    """
}

process AGGREGATE {
    tag "$meta.id"
    label 'process_medium'

    /* container "community.wave.seqera.io/library/python_sopa:54a97bc5a187152d" */
    container '/fast/AG_Coscia/software/singularity/python_sopa.sif'

    input:
    tuple val(meta), path(sdata)

    output:
    tuple val(meta), path(sdata), emit: sdata_aggregated

    script:
    """
    export HOME=\$PWD
    export NUMBA_CACHE_DIR=\$PWD
    export MPLCONFIGDIR=\$PWD

    sopa aggregate $sdata --no-aggregate-genes --aggregate-channels
    """

    stub:
    """
    mkdir -p $sdata
    """
}

process MERGE_SPATIALDATA {
    tag "$sample_id"
    label 'process_medium'
    publishDir "${params.outdir}/sopa", mode: 'copy'

    /* container "community.wave.seqera.io/library/python_sopa:54a97bc5a187152d" */
    container '/fast/AG_Coscia/software/singularity/python_sopa.sif'

    input:
    tuple val(sample_id), path(core_zarrs)

    output:
    tuple val(meta), path("*.zarr"), emit: merged_sdata

    script:
    meta = [ id: "${sample_id}_merged" ]
    """
    export HOME=\$PWD
    export NUMBA_CACHE_DIR=\$PWD
    export MPLCONFIGDIR=\$PWD

    python3 $projectDir/bin/merge_spatialdata.py ${sample_id}_merged.zarr $core_zarrs
    """

    stub:
    meta = [ id: "${sample_id}_merged" ]
    """
    mkdir -p ${sample_id}_merged.zarr
    touch ${sample_id}_merged.zarr/.zgroup
    """
}

process EXPLORER {
    tag "$meta.id"
    label 'process_medium'
    publishDir "${params.outdir}/explorer", mode: 'copy'

    /* container "community.wave.seqera.io/library/python_sopa:54a97bc5a187152d" */
    container '/fast/AG_Coscia/software/singularity/python_sopa.sif'

    input:
    tuple val(meta), path(sdata)

    output:
    tuple val(meta), path("*.explorer"), emit: explorer

    script:
    def prefix = "${meta.id}"
    """
    export HOME=\$PWD
    export NUMBA_CACHE_DIR=\$PWD
    export MPLCONFIGDIR=\$PWD

    sopa explorer write $sdata --output-path ${prefix}.explorer
    """

    stub:
    def prefix = "${meta.id}"
    """
    mkdir -p ${prefix}.explorer
    """
}

process REPORT {
    tag "$meta.id"
    label 'process_low'
    publishDir "${params.outdir}/report", mode: 'copy'

    /* container "community.wave.seqera.io/library/python_sopa:54a97bc5a187152d" */
    container '/fast/AG_Coscia/software/singularity/python_sopa.sif'

    input:
    tuple val(meta), path(sdata)

    output:
    tuple val(meta), path("*.html"), emit: html_report

    script:
    def prefix = "${meta.id}"
    """
    export HOME=\$PWD
    export NUMBA_CACHE_DIR=\$PWD
    export MPLCONFIGDIR=\$PWD

    sopa report $sdata ${prefix}.html
    """

    stub:
    def prefix = "${meta.id}"
    """
    touch ${prefix}.html
    """
}

workflow SOPA_SPATIAL {
    take:
    ch_images // channel: [ meta, ome_tiff ]

    main:
    // 1. Convert optical TIFF image into SpatialData Zarr format
    TO_SPATIALDATA( ch_images )

    // 2. Divide SpatialData image into processing patches
    MAKE_IMAGE_PATCHES( TO_SPATIALDATA.out.sdata )

    // Flatten patches for parallel Cellpose execution
    ch_patches = MAKE_IMAGE_PATCHES.out.sdata_patches.flatMap { meta, sdata, num_patches_file ->
        def n = num_patches_file.text.trim().toInteger()
        (0..<n).collect { i -> [ meta, sdata, i ] }
    }

    // 3. Parallel patch segmentation
    PATCH_SEGMENTATION_CELLPOSE( ch_patches )

    // Group patch parquet outputs back by sample meta
    ch_grouped_parquets = PATCH_SEGMENTATION_CELLPOSE.out.patch_parquet
        .map { meta, sdata, parquet -> [ meta, sdata, parquet ] }
        .groupTuple(by: 0)
        .map { meta, sdatas, parquets -> [ meta, sdatas[0], parquets ] }

    // 4. Resolve patch boundary collisions
    RESOLVE_CELLPOSE( ch_grouped_parquets )

    // 5. Aggregate transcripts / channels per segmented cell
    AGGREGATE( RESOLVE_CELLPOSE.out.sdata_resolved )

    // Group individual core Zarr stores by sample ID for merging (if sample attribute exists)
    ch_grouped_cores = AGGREGATE.out.sdata_aggregated
        .map { meta, sdata -> [ meta.sample ? meta.sample : meta.id, sdata ] }
        .groupTuple(by: 0)

    // 6. Merge core SpatialData objects into unified master SpatialData Zarr
    MERGE_SPATIALDATA( ch_grouped_cores )

    // 7. Export Xenium Explorer & HTML QC report for each individual core
    EXPLORER( AGGREGATE.out.sdata_aggregated )
    REPORT( AGGREGATE.out.sdata_aggregated )

    emit:
    merged_sdata = MERGE_SPATIALDATA.out.merged_sdata
    core_sdata   = AGGREGATE.out.sdata_aggregated
    explorer     = EXPLORER.out.explorer
    report       = REPORT.out.html_report
}
