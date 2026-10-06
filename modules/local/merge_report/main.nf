process MERGE_REPORT {
    // Slide-level page built only from per-core QC_METRICS JSON; it measures nothing itself.
    label 'process_single'
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    // meta is the slide; core_metrics holds every core of it.
    tuple val(meta), path(core_metrics)

    output:
    tuple val(meta), path("${meta.sample}_slide_report.html"), emit: report
    path "versions.yml"                                      , emit: versions

    script:
    def args = task.ext.args ?: ""
    """
    merge_report.py \\
        --metrics ${core_metrics} \\
        --slide ${meta.sample} \\
        --out ${meta.sample}_slide_report.html \\
        ${args}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """

    stub:
    """
    touch ${meta.sample}_slide_report.html

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: stub
    END_VERSIONS
    """
}
