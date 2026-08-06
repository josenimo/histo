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
    def strict_channels = params.require_channel_names ? 'true' : 'false'
    """
    sopa convert ${data_dir} --sdata-path ${meta.sdata_dir} ${argsToSpatialData(meta, fullres_image_file.toString())} 2>&1 | tee sopa_convert.log

    # sopa's ome_tif reader falls back to integer channel names when the OME-XML
    # has none, and reports it with log.warning only. For an unattended run on a
    # colleague's data that means every marker name is silently replaced by its
    # index, and nothing downstream notices: the feature table just has columns
    # called 0, 1, 2.
    #
    # Not fatal by default, because the preprocessing half does not yet write
    # channel names into the OME-XML it hands over. See ROADMAP.md section 6.
    # Set require_channel_names to turn this into a hard failure once it does.
    if grep -q "Channel names couldn't be read" sopa_convert.log; then
        echo "" >&2
        echo "########################################################################" >&2
        echo "# CHANNEL NAMES LOST for ${meta.sample}" >&2
        echo "#" >&2
        echo "# sopa could not read channel names from the OME-XML and has replaced" >&2
        echo "# them with integers. Marker names will NOT appear in the feature table." >&2
        echo "# See ROADMAP.md section 6 for the fix." >&2
        echo "########################################################################" >&2
        echo "" >&2
        if [ "${strict_channels}" = "true" ]; then
            echo "require_channel_names is set, so this is fatal." >&2
            exit 1
        fi
    fi

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
