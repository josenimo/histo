process QC_REPORT {
    // bin/qc_report.py uses only the standard library.
    label "process_single"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    // image_dir is optional ([] when use_qc_images is false).
    tuple val(meta), path(metrics), path(image_dir)

    output:
    tuple val(meta), path("${meta.sample}_qc_report.html"), emit: report
    path "versions.yml"                                   , emit: versions

    script:
    def args = task.ext.args ?: ""
    def images = image_dir ? "--images ${image_dir}/qc_images.json" : ""
    """
    qc_report.py \\
        --metrics ${metrics} \\
        --out ${meta.sample}_qc_report.html \\
        ${images} \\
        ${args}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """

    stub:
    """
    touch ${meta.sample}_qc_report.html

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: stub
    END_VERSIONS
    """
}
