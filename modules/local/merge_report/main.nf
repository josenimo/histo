process MERGE_REPORT {
    // One page for a dearrayed slide, from the per-core metrics QC_METRICS already
    // wrote. Like QC_REPORT it reads JSON and writes HTML, so it needs nothing from
    // the container beyond a Python interpreter, and it measures nothing itself --
    // a number here cannot disagree with the core report it came from.
    label 'process_single'
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    // Every core of one slide, grouped. meta is the slide rather than a core, which
    // is what makes this one task per slide instead of one per core.
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
