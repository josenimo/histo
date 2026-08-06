process REPORT {
    label "process_medium"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    publishDir "${params.outdir}", mode: params.publish_dir_mode

    input:
    tuple val(meta), path(sdata_path)

    output:
    // sdata is emitted so that MERGE_SPATIALDATA can chain off REPORT rather
    // than fanning off the same upstream channel. The sopa modules mutate the
    // zarr in place and this one deletes .sopa_cache from it, so a concurrent
    // reader would be racing a writer.
    tuple val(meta), path(sdata_path)           , emit: sdata
    path "${meta.sample}_analysis_summary.html" , emit: report
    path "versions.yml"                         , emit: versions

    script:
    // Upstream sopa wrote this into the Xenium Explorer directory, so that the
    // report shipped alongside the Explorer bundle. EXPLORER has been removed
    // from this pipeline, so the report is published as a flat per-sample file
    // rather than alone inside a directory named after a step that no longer runs.
    """
    sopa report ${sdata_path} ${meta.sample}_analysis_summary.html

    rm -r ${sdata_path}/.sopa_cache || true # clean up cache if existing

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        sopa: \$(sopa --version)
    END_VERSIONS
    """

    stub:
    """
    touch ${meta.sample}_analysis_summary.html

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        sopa: stub
    END_VERSIONS
    """
}
