process AGGREGATE {
    label "process_medium"
    tag "${meta.sample}"

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
?         'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe/data'
:         'community.wave.seqera.io/library/python_sopa:54a97bc5a187152d' }"

    input:
    tuple val(meta), path(sdata_path)
    val cli_arguments

    output:
    tuple val(meta), path(sdata_path)
    path "versions.yml"

    script:
    // Not from sopa: replaces sopa's obs/slide (image element name) with the samplesheet slide;
    // meta.slide is set only on dearrayed TMAs, where meta.id is the core.
    def core_id_arg = meta.slide ? "--core-id ${meta.id}" : ""
    """
    sopa aggregate ${sdata_path} ${cli_arguments}

    set_cell_metadata.py \\
        --sdata ${sdata_path} \\
        --slide ${meta.slide ?: meta.sample} \\
        ${core_id_arg}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        sopa: \$(sopa --version)
    END_VERSIONS
    """

    stub:
    """
    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        sopa: stub
    END_VERSIONS
    """
}
