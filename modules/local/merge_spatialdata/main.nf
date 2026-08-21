process MERGE_SPATIALDATA {
    label "process_medium"
    tag "${meta.id}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    // One entry per slide. `core_zarrs` are the finished per-core stores, staged
    // under their own names on purpose: merge_spatialdata.py derives each core's
    // ID from its directory name, so renaming them here would destroy the IDs.
    tuple val(meta), path(core_zarrs)

    output:
    tuple val(meta), path("${meta.id}_merged.zarr"), emit: merged
    path "${meta.id}_merge_manifest.json"          , emit: manifest
    path "versions.yml"                            , emit: versions

    script:
    """
    merge_spatialdata.py \\
        --output ${meta.id}_merged.zarr \\
        --manifest ${meta.id}_merge_manifest.json \\
        ${core_zarrs}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        spatialdata: \$(python -c "import spatialdata; print(spatialdata.__version__)" 2> /dev/null)
    END_VERSIONS
    """

    stub:
    """
    mkdir -p ${meta.id}_merged.zarr
    touch ${meta.id}_merged.zarr/.zgroup
    echo '{}' > ${meta.id}_merge_manifest.json

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        spatialdata: stub
    END_VERSIONS
    """
}
