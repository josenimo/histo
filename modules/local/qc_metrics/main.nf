process QC_METRICS {
    label "process_low"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    // `unsubtracted` is the pre-background-subtraction image, and it is optional: pass
    // [] and the before-and-after comparison is simply absent from the JSON. It has to
    // come in as an input rather than be read from the publish directory, because a
    // task must not depend on another task's published output -- that is not staged,
    // and with -resume it may not exist.
    // markers is per sample, carried in the tuple so it is matched by key rather
    // than broadcast.
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
