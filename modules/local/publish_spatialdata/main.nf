process PUBLISH_SPATIALDATA {
    label "process_single"
    tag "${meta.sample}"

    publishDir "${params.outdir}", mode: params.publish_dir_mode

    input:
    tuple val(meta), path(sdata_path)

    output:
    tuple val(meta), path(sdata_path), emit: sdata

    script:
    // A publish sink, and deliberately empty. publishDir is a process directive,
    // so publishing a channel means declaring it as some process's output. The
    // store is finished by the time it arrives: AGGREGATE and FLUO_ANNOTATION
    // have already written into it, and which of them ran last depends on
    // use_fluorescence_annotation, so attaching publishDir to either would
    // publish a store that the other then mutates in place.
    //
    // This replaces REPORT, which published the store as a side effect of
    // rendering sopa's HTML summary. The rendering moved to QC_REPORT; the
    // publication needed a home of its own.
    //
    // No tool runs, so there is no version to record. See .lint-allow-no-versions.
    """
    true
    """

    stub:
    """
    true
    """
}
