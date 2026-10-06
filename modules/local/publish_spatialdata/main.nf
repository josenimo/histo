process PUBLISH_SPATIALDATA {
    label "process_single"
    tag "${meta.sample}"

    publishDir "${params.outdir}", mode: params.publish_dir_mode

    input:
    tuple val(meta), path(sdata_path)

    output:
    tuple val(meta), path(sdata_path), emit: sdata

    script:
    // Empty publish sink: publishDir on AGGREGATE or FLUO_ANNOTATION would publish a store
    // that may still be mutated. No tool, so no versions (see .lint-allow-no-versions).
    """
    true
    """

    stub:
    """
    true
    """
}
