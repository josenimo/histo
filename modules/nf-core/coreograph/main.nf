process COREOGRAPH {
    tag "$meta.id"
    label 'process_single'

    container "docker.io/labsyspharm/unetcoreograph:2.4.6"

    input:
    tuple val(meta), path(image)

    output:
    tuple val(meta), path("*_core[0-9][0-9][0-9].*tif")          , emit: cores
    tuple val(meta), path("masks/*_core[0-9][0-9][0-9]_mask.*tif"), emit: masks
    tuple val(meta), path("*_tma_map.tif")                       , emit: tma_map
    tuple val(meta), path("*_coremask.tif")                      , emit: coremask
    tuple val(meta), path("*_centroids.txt")                     , emit: centroids
    tuple val("${task.process}"), val('coreograph'), val("2.4.6"), topic: versions, emit: versions_coreograph
    // WARN: Version information not provided by tool on CLI. Please update this string when bumping container versions.

    when:
    task.ext.when == null || task.ext.when

    script:
    def args    = task.ext.args ?: ''
    def prefix  = task.ext.prefix ?: "${meta.id}"

    """
    export MPLCONFIGDIR=\$PWD

    python /app/UNetCoreograph.py \\
        --imagePath ${image} \\
        --outputPath . \\
        $args

    # PATCH: give every output the slide's identity.
    #
    # UNetCoreograph names cores by bare number, so a core is "1.ome.tif" with
    # nothing linking it to the slide it came from. sopa derives SpatialData
    # element names from the filename up to the first dot, so those cores would
    # enter the downstream half as elements named "1" and "2". TMA_MAP.tif,
    # Coremask.tif and centroidsY-X.txt are fixed names and would collide between
    # slides published to the same directory.
    #
    # The original core number is preserved rather than re-indexed, so the mapping
    # from a core to its row in the centroids file survives.
    #
    # Extension handling is deliberately generic. 2.2.9 wrote "1.tif" and 2.4.6
    # writes "1.ome.tif"; \${f%%.*} takes the name up to the first dot and
    # \${f#*.} keeps whatever extension chain followed, so this survives the
    # change rather than silently renaming nothing.
    #
    # The purely-numeric test matters: the staged input is also a .tif containing
    # digits, and the glob would otherwise rename it.
    for f in *.tif; do
        [ -e "\$f" ] || continue
        n=\${f%%.*}
        ext=\${f#*.}
        case "\$n" in *[!0-9]*) continue ;; esac
        mv "\$f" "${prefix}_core\$(printf '%03d' "\$n").\$ext"
    done

    for f in masks/*; do
        [ -e "\$f" ] || continue
        b=\$(basename "\$f")
        n=\${b%%[!0-9]*}
        [ -n "\$n" ] || continue
        rest=\${b#\$n}
        mv "\$f" "masks/${prefix}_core\$(printf '%03d' "\$n")\${rest%%.*}.\${b#*.}"
    done

    mv TMA_MAP.tif "${prefix}_tma_map.tif"
    mv Coremask.tif "${prefix}_coremask.tif"
    mv centroidsY-X.txt "${prefix}_centroids.txt"
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    # Mirrors 2.4.6 exactly, including its inconsistency: cores are written as
    # .ome.tif but masks as plain .tif. 2.2.9 wrote cores as .tif. The rename in
    # the script block is extension-agnostic and the globs accept either, but the
    # stub should reflect what the tool really does.
    touch ${prefix}_core001.ome.tif
    touch ${prefix}_core002.ome.tif
    mkdir -p masks
    touch masks/${prefix}_core001_mask.tif
    touch masks/${prefix}_core002_mask.tif
    touch ${prefix}_tma_map.tif
    touch ${prefix}_coremask.tif
    touch ${prefix}_centroids.txt
    """
}
