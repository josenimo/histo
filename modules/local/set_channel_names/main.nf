process SET_CHANNEL_NAMES {
    label "process_single"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    // markers arrives in the tuple rather than as a separate input, so it is matched
    // to its own store by key. As a separate `path` input it was a single file
    // broadcast to every sample, which silently processed one sample and dropped the
    // rest whenever that channel held one item rather than being a value channel.
    tuple val(meta), path(sdata_path), path(markers)

    output:
    // Pass-through: this mutates the store in place and declares its input as its
    // output, the same shape as the sopa modules. Only ~5 KB of group metadata
    // changes, so it costs the same on a 320 MB image as on a 100 GB one.
    tuple val(meta), path(sdata_path), emit: sdata
    path "versions.yml"              , emit: versions

    script:
    // No --element. The channel labels come from the marker sheet; the element name
    // was only ever an address for which image inside the store to write them onto,
    // and passing meta.sample tied that address to the input filename.
    //
    // Those two agree only by luck. sopa convert names the image element after the
    // stem of the file it converted, so any step that renames the image breaks the
    // lookup: with use_backsub the element is {sample}_backsub while meta.sample is
    // still {sample}, and the run dies with "no image element".
    //
    // Without --element the script takes the sole image element and fails if there
    // is more than one. After conversion there is exactly one, and on the TMA path
    // each core is its own store, so nothing is weakened: the guard is now "exactly
    // one image" rather than "an image with this name", which is the property we
    // actually depend on.
    """
    set_channel_names.py \\
        --sdata ${sdata_path} \\
        --markers ${markers}

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
