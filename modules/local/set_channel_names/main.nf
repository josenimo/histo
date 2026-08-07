process SET_CHANNEL_NAMES {
    label "process_single"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    tuple val(meta), path(sdata_path)
    path markers

    output:
    // Pass-through: this mutates the store in place and declares its input as its
    // output, the same shape as the sopa modules. Only ~5 KB of group metadata
    // changes, so it costs the same on a 320 MB image as on a 100 GB one.
    tuple val(meta), path(sdata_path), emit: sdata
    path "versions.yml"              , emit: versions

    script:
    """
    set_channel_names.py \\
        --sdata ${sdata_path} \\
        --markers ${markers} \\
        --element ${meta.sample}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        spatialdata: \$(python -c "import spatialdata; print(spatialdata.__version__)" 2> /dev/null)
    END_VERSIONS
    """

    stub:
    """
    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        spatialdata: stub
    END_VERSIONS
    """
}
