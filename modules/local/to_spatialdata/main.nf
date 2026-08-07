include { argsToSpatialData } from '../utils'

process TO_SPATIALDATA {
    label "process_high"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    tuple val(meta), path(data_dir), path(fullres_image_file)

    output:
    tuple val(meta), path("${meta.sdata_dir}")
    path "versions.yml"

    script:
    // A guard used to live here: it grepped sopa's log for "Channel names couldn't
    // be read" and, with require_channel_names, made that fatal. It was removed
    // because it never fired and could not.
    //
    // sopa only logs that message when it finds no names at all. What Ashlar
    // actually produces is Channel elements carrying `id` and no `Name`, so sopa
    // reads the IDs and reports success while naming every channel `Channel:0:N`.
    // The guard tested a log message that merely correlated with the property we
    // cared about, and the correlation did not hold.
    //
    // SET_CHANNEL_NAMES now sets the names from the marker sheet immediately after
    // this step, and fails loudly if the sheet and the image disagree on channel
    // count. That checks the thing itself rather than a proxy for it.
    """
    sopa convert ${data_dir} --sdata-path ${meta.sdata_dir} ${argsToSpatialData(meta, fullres_image_file.toString())}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        sopa: \$(sopa --version)
        spatialdata: \$(python -c "import spatialdata; print(spatialdata.__version__)" 2> /dev/null)
        spatialdata_io: \$(python -c "import spatialdata_io; print(spatialdata_io.__version__)" 2> /dev/null)
    END_VERSIONS
    """

    stub:
    """
    mkdir -p ${meta.sdata_dir}
    touch ${meta.sdata_dir}/.zgroup

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        sopa: stub
        spatialdata: stub
        spatialdata_io: stub
    END_VERSIONS
    """
}
