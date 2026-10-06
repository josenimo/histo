process QC_IMAGES {
    // Separate from QC_METRICS because it is slow (neighbour graph, polygon rasterising).
    label "process_medium"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    tuple val(meta), path(sdata_path), path(markers)

    output:
    // A directory, since the number of PNGs depends on the number of clusters.
    tuple val(meta), path("${meta.sample}_qc_images"), emit: images
    path "versions.yml"                              , emit: versions

    script:
    def args = task.ext.args ?: ""
    def sheet = markers ? "--markers ${markers}" : ""
    """
    qc_images.py \\
        --sdata ${sdata_path} \\
        --out-dir ${meta.sample}_qc_images \\
        ${sheet} \\
        ${args}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
        scanpy: \$(python -c "import scanpy; print(scanpy.__version__)")
        igraph: \$(python -c "import igraph; print(igraph.__version__)")
        geopandas: \$(python -c "import geopandas; print(geopandas.__version__)")
    END_VERSIONS
    """

    stub:
    """
    mkdir -p ${meta.sample}_qc_images
    echo '{"sample": "${meta.sample}", "crops": [], "stub": true}' \\
        > ${meta.sample}_qc_images/qc_images.json

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: stub
        scanpy: stub
        igraph: stub
        geopandas: stub
    END_VERSIONS
    """
}
