// Function library vendored from nf-core/sopa at c2b4e5f. New sopa params must also be added to extractSubArgs().
// Kept flat despite lint (local_component_structure): as utils/main.nf it fails the stub/versions hooks.

def stringifyItem(String key, value) {
    key = key.replace('_', '-')

    def option = "--${key}"

    if (value instanceof Boolean) {
        return value ? option : "--no-${key}"
    }
    if (value instanceof List) {
        return value.collect { v -> "${option} ${stringifyValueForCli(v)}" }.join(" ")
    }
    if (value instanceof Map) {
        return "${option} \"" + stringifyValueForCli(value) + "\""
    }
    return "${option} ${stringifyValueForCli(value)}"
}

def stringifyValueForCli(value) {
    if (value instanceof Map) {
        return "{" + value.collect { k, v -> "'${k}': ${stringifyValueForCli(v)}" }.join(", ") + "}"
    }
    if (value instanceof List) {
        return "[" + value.collect { stringifyValueForCli(it) }.join(", ") + "]"
    }
    if (value instanceof String) {
        return "'${value}'"
    }
    if (value instanceof Boolean) {
        return value ? "True" : "False"
    }
    if (value instanceof Number) {
        return value.toString()
    }
    return "'${value.toString()}'"
}

def extractSubArgs(Map args, String group) {
    if (group == "cellpose") {
        return [
            diameter: args.cellpose_diameter,
            channels: getChannels(args.cellpose_channels, false),
            flow_threshold: args.flow_threshold,
            cellprob_threshold: args.cellprob_threshold,
            model_type: args.cellpose_model_type,
            pretrained_model: args.pretrained_model,
            gpu: args.cellpose_use_gpu,
            min_area: args.min_area_pixels2,
            clip_limit: args.clip_limit,
            clahe_kernel_size: args.clahe_kernel_size,
            gaussian_sigma: args.gaussian_sigma,
            method_kwargs: args.cellpose_kwargs,
        ]
    } else if (group == "stardist") {
        return [
            model_type: args.stardist_model_type,
            prob_thresh: args.prob_thresh,
            nms_thresh: args.nms_thresh,
            channels: getChannels(args.stardist_channels, true),
            min_area: args.min_area_pixels2,
            clip_limit: args.clip_limit,
            clahe_kernel_size: args.clahe_kernel_size,
            gaussian_sigma: args.gaussian_sigma,
            method_kwargs: args.stardist_kwargs,
        ]
    } else if (group == "aggregate") {
        return [
            aggregate_genes: args.aggregate_genes,
            aggregate_channels: args.aggregate_channels,
            expand_radius_ratio: args.expand_radius_ratio,
            min_transcripts: args.min_transcripts,
            min_intensity_ratio: args.min_intensity_ratio,
        ]
    } else if (group == "tissue_segmentation") {
        return [
            level: args.level,
            mode: args.mode,
            kwargs: args.tissue_segmentation_kwargs,
        ]
    } else if (group == "image_patches") {
        return [
            patch_width_pixel: args.patch_width_pixel,
            patch_overlap_pixel: args.patch_overlap_pixel,
            scale: args.image_scale,
        ]
    } else if (group == "fluorescence_annotation") {
        return [
            cell_type_key: args.fluorescence_cell_type_key,
            marker_cell_dict: args.marker_cell_dict,
        ]
    } else {
        exit 1, "Unknown argument group: ${group}"
    }
}

// Channels may be a string or a number (schema type ["string", "integer"]); left untyped so
// Groovy does not coerce silently.
def getChannels(channels, Boolean allow_null = false) {
    if (channels == null) {
        if (allow_null) {
            return null
        }
        exit 1, "The channels parameter is required but was not set."
    }

    if (!(channels instanceof CharSequence) && !(channels instanceof Number)) {
        exit 1, "The channels parameter must be channel names separated by space, comma or " +
            "pipe characters, or a single channel number. Got a ${channels.getClass().simpleName}: ${channels}"
    }

    return channels.toString().split(/[ ,|]+/).findAll { it }
}

def argsCLI(String group = null, Map args = null) {
    args = args ?: params

    if (group != null) {
        args = extractSubArgs(args, group)
    }

    return args
        .findAll { _key, _value -> _value != null }
        .collect { key, value -> stringifyItem(key, value) }
        .join(" ")
}


def argsToSpatialData(Map meta, String fullres_image_file) {
    def args = [
        technology: params.technology,
        kwargs: [:],
    ]

    return argsCLI(null, args)
}
