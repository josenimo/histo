process QC_METRICS {
    label "process_low"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    // unsubtracted (pre-backsub image) and markers are optional; pass [] to omit.
    tuple val(meta), path(sdata_path), path(unsubtracted), path(markers)

    output:
    tuple val(meta), path("${meta.sample}_qc.json"), emit: metrics
    path "versions.yml"                            , emit: versions

    script:
    def args = task.ext.args ?: ""
    def before = unsubtracted ? "--before-image ${unsubtracted}" : ""
    def sheet = markers ? "--markers ${markers}" : ""
    """
    qc_metrics.py \\
        --sdata ${sdata_path} \\
        --out ${meta.sample}_qc.json \\
        ${sheet} \\
        ${before} \\
        ${args}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
        numpy: \$(python -c "import numpy; print(numpy.__version__)")
        zarr: \$(python -c "import zarr; print(zarr.__version__)")
    END_VERSIONS
    """

    stub:
    """
    echo '{"sample": "${meta.sample}", "stub": true}' > ${meta.sample}_qc.json

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: stub
        numpy: stub
        zarr: stub
    END_VERSIONS
    """
}
