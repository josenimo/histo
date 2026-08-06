//
// Function library, not a process. Vendored from nf-core/sopa at c2b4e5f.
//
// argsCLI() maps the flat parameters in nextflow.config into command-line strings
// for the sopa CLI, skipping nulls. extractSubArgs() defines which parameters
// belong to which step. Adding a parameter to nextflow.config is not enough; it
// must also be listed here or it will never reach the tool.
//
// ACCEPTED LINT WARNING: `local_component_structure` says this should live at
// modules/local/utils/main.nf. It is deliberately left flat, because it contains
// no process. Moving it would bring it into the scope of the module-has-stub and
// module-emits-versions pre-commit hooks, which glob modules/local/*/main.nf, and
// it would fail both: a function library has neither a stub block nor a version
// to report. The flat file is more honest about what this is. The warning is
// accepted rather than exempted, since exempting would disable the check for
// every local module and hide a genuine violation later.
//

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

//
// Channel names arrive as a string, but may legitimately be a number.
//
// The schema declares these parameters as ["string", "integer"], on nf-schema's own
// recommendation for identifier-like fields: a value of `0` is inferred as an integer
// somewhere between the params file and validation, and fails a plain "string" schema
// with `Value is [integer] but should be [string]` before the pipeline even starts.
//
// This bites here specifically because channel names are currently integers. Ashlar
// does not write marker names into the OME-XML, so sopa falls back to naming channels
// 0..N and the only way to address one is by number. Once ROADMAP section 6 lands and
// real marker names reach the zarr, the integer case becomes vestigial rather than the
// normal one, but numeric channel names remain legal so this stays.
//
// The parameter is deliberately untyped. Declaring it `String` made Groovy coerce
// silently, which hid what was happening.
//
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
