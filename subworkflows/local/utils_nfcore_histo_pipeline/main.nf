//
// Subworkflow with functionality specific to the josenimo/histo pipeline
//

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    IMPORT FUNCTIONS / MODULES / SUBWORKFLOWS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

include { UTILS_NFSCHEMA_PLUGIN     } from '../../nf-core/utils_nfschema_plugin'
include { paramsSummaryMap          } from 'plugin/nf-schema'
include { samplesheetToList         } from 'plugin/nf-schema'
include { completionEmail           } from '../../nf-core/utils_nfcore_pipeline'
include { completionSummary         } from '../../nf-core/utils_nfcore_pipeline'
include { UTILS_NFCORE_PIPELINE     } from '../../nf-core/utils_nfcore_pipeline'
include { UTILS_NEXTFLOW_PIPELINE   } from '../../nf-core/utils_nextflow_pipeline'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    SUBWORKFLOW TO INITIALISE PIPELINE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow PIPELINE_INITIALISATION {
    take:
    version // boolean: Display version and exit
    validate_params // boolean: Boolean whether to validate parameters against the schema at runtime
    monochrome_logs // boolean: Do not use coloured log outputs
    nextflow_cli_args //   array: List of positional nextflow CLI args
    outdir //  string: The output directory where the results will be saved
    input //  string: Path to input samplesheet
    help // boolean: Display help message and exit
    help_full // boolean: Show the full help message
    show_hidden // boolean: Show hidden parameters in the help message

    main:

    ch_versions = channel.empty()

    //
    // Print version and exit if required and dump pipeline parameters to JSON file
    //
    UTILS_NEXTFLOW_PIPELINE(
        version,
        true,
        outdir,
        workflow.profile.tokenize(',').intersect(['conda', 'mamba']).size() >= 1,
    )

    //
    // Validate parameters and generate parameter summary to stdout
    //

    def before_text = ""
    def after_text = ""
    before_text = """
-\033[2m----------------------------------------------------\033[0m-
\033[0;35m  ${workflow.manifest.name} ${workflow.manifest.version}\033[0m
\033[2m  ${workflow.manifest.description}\033[0m
-\033[2m----------------------------------------------------\033[0m-
"""
    after_text = """
* The nf-core framework
    https://doi.org/10.1038/s41587-020-0439-x

* Software dependencies
    https://github.com/josenimo/histo/blob/main/CITATIONS.md
"""
    if (monochrome_logs) {
        before_text = before_text.replaceAll(/\033\[[0-9;]*m/, '')
    }

    command = "nextflow run ${workflow.manifest.name} -profile <docker/singularity/.../institute> --input samplesheet.csv --outdir <OUTDIR>"

    UTILS_NFSCHEMA_PLUGIN(
        workflow,
        validate_params,
        null,
        help,
        help_full,
        show_hidden,
        before_text,
        after_text,
        command,
        // cast_cli_params: CLI values arrive as strings and would fail number/boolean validation
        true,
    )

    //
    // Check config provided to the pipeline
    //
    UTILS_NFCORE_PIPELINE(
        nextflow_cli_args
    )

    //
    // Create channel from input file provided through params.input
    // use_preprocessing: one row per acquisition cycle; otherwise one row per sample, already sopa-readable.
    // cycle_rows is declared here because the marker sheet block below also needs it.
    def cycle_rows = null

    if (params.use_preprocessing) {
        // Rows are [meta, image_tiles, dfp, ffp, marker_sheet], in schema property order.
        cycle_rows = samplesheetToList(params.input, "${projectDir}/assets/schema_input_cycle.json")

        validateIlluminationColumns(cycle_rows)
        validateCycleNumbers(cycle_rows)
        validateMarkerSheetColumn(cycle_rows)

        Channel
            .fromList(cycle_rows)
            .map { meta, image_tiles, dfp, ffp, _marker_sheet ->
                // sdata_dir and marker_sheet are per sample, so both are attached after stitching
                // (marker_sheet via ch_markersheet).
                [meta, image_tiles, dfp, ffp]
            }
            .set { ch_samplesheet }
    }
    else {
        Channel
            .fromList(samplesheetToList(params.input, "${projectDir}/assets/schema_input.json"))
            .map { meta, data_path ->
                if (!data_path) {
                    error("The `data_path` column must be provided when use_preprocessing is false")
                }

                if (!meta.sample) {
                    meta.sample = file(data_path).baseName
                }

                meta.data_dir = data_path
                meta.sdata_dir = "${meta.sample}.zarr"

                return meta
            }
            .set { ch_samplesheet }
    }

    // Params validation
    rejectSpacedBooleans(workflow.commandLine)
    rejectStringBooleans(params)
    rejectUnknownParams(params)
    validateParams(params)

    // Marker sheets, one per sample, emitted as paths (each consumer parses the CSV itself).
    // Validated here, not in a channel operator, where a failed assert dies without a message.
    if (params.use_preprocessing) {
        def sheets_by_sample = markerSheetsBySample(cycle_rows)

        // Every marker sheet column is declared as meta, so each row is [meta], hence it[0].
        sheets_by_sample.each { sample, sheet ->
            def rows = samplesheetToList(sheet, "${projectDir}/assets/schema_marker.json").collect { it[0] }
            validateMarkersheet(rows, sample)
            checkReferenceChannels(rows, sample)
        }

        ch_markersheet = channel.fromList(
            sheets_by_sample.collect { sample, sheet -> [[id: sample], file(sheet)] }
        )
    }
    else {
        // Pre-stitched images are assumed to carry their own channel names.
        ch_markersheet = channel.empty()
    }

    emit:
    samplesheet = ch_samplesheet
    markersheet = ch_markersheet
    versions = ch_versions
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    SUBWORKFLOW FOR PIPELINE COMPLETION
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow PIPELINE_COMPLETION {
    take:
    email //  string: email address
    email_on_fail //  string: email address sent on pipeline failure
    plaintext_email // boolean: Send plain-text email instead of HTML
    outdir //    path: Path to output directory where results will be published
    monochrome_logs // boolean: Disable ANSI colour codes in log output

    main:
    summary_params = paramsSummaryMap(workflow, parameters_schema: "nextflow_schema.json")

    //
    // Completion email and summary
    //
    workflow.onComplete {
        if (email || email_on_fail) {
            completionEmail(
                summary_params,
                email,
                email_on_fail,
                plaintext_email,
                outdir,
                monochrome_logs,
                [],
            )
        }

        completionSummary(monochrome_logs)

    }

    workflow.onError {
        log.error "Pipeline failed. Please refer to troubleshooting docs for common issues: https://nf-co.re/docs/running/troubleshooting"
    }
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

//
// Generate methods description for MultiQC
//
def toolCitationText() {
    def citation_text = [
        "Tools used in the workflow included:",
        "Sopa (Blampey et al. 2024),",
        "AnnData (Virshup et al. 2021),",
        "Scanpy (Wolf et al. 2018),",
        "Space Ranger (10x Genomics)",
        "SpatialData (Marconato et al. 2023) and",
    ].join(' ').trim()

    return citation_text
}

def toolBibliographyText() {
    def reference_text = [
        '<li>Di Tommaso, P., Chatzou, M., Floden, E. W., Barja, P. P., Palumbo, E., & Notredame, C. (2017). Nextflow enables reproducible computational workflows. Nature Biotechnology, 35(4), 316-319. doi: <a href="https://doi.org/10.1038/nbt.3820">10.1038/nbt.3820</a></li>',
        '<li>Ewels, P. A., Peltzer, A., Fillinger, S., Patel, H., Alneberg, J., Wilm, A., Garcia, M. U., Di Tommaso, P., & Nahnsen, S. (2020). The nf-core framework for community-curated bioinformatics pipelines. Nature Biotechnology, 38(3), 276-278. doi: <a href="https://doi.org/10.1038/s41587-020-0439-x">10.1038/s41587-020-0439-x</a></li>',
        '<li>Grüning, B., Dale, R., Sjödin, A., Chapman, B. A., Rowe, J., Tomkins-Tinch, C. H., Valieris, R., Köster, J., & Bioconda Team. (2018). Bioconda: sustainable and comprehensive software distribution for the life sciences. Nature Methods, 15(7), 475–476. doi: <a href="https://doi.org/10.1038/s41592-018-0046-7">10.1038/s41592-018-0046-7</a></li>',
        '<li>da Veiga Leprevost, F., Grüning, B. A., Alves Aflitos, S., Röst, H. L., Uszkoreit, J., Barsnes, H., Vaudel, M., Moreno, P., Gatto, L., Weber, J., Bai, M., Jimenez, R. C., Sachsenberg, T., Pfeuffer, J., Vera Alvarez, R., Griss, J., Nesvizhskii, A. I., & Perez-Riverol, Y. (2017). BioContainers: an open-source and community-driven framework for software standardization. Bioinformatics (Oxford, England), 33(16), 2580–2582. doi: <a href="https://doi.org/10.1093/bioinformatics/btx192">10.1093/bioinformatics/btx192</a></li>',
        '<li>Quentin Blampey, Kevin Mulder, Margaux Gardet, Stergios Christodoulidis, Charles-Antoine Dutertre, Fabrice André, Florent Ginhoux & Paul-Henry Cournède. Sopa: a technology-invariant pipeline for analyses of image-based spatial omics. Nat Commun 2024 June 11. doi: <a href="https://dx.doi.org/10.1038/s41587-020-0439-x">10.1038/s41587-020-0439-x</a></li>',
        '<li>Virshup I, Rybakov S, Theis FJ, Angerer P, Wolf FA. bioRxiv 2021.12.16.473007. doi: <a href="https://doi.org/10.1101/2021.12.16.473007">10.1101/2021.12.16.473007</a></li>',
        '<li>Wolf F, Angerer P, Theis F. SCANPY: large-scale single-cell gene expression data analysis. Genome Biol 19, 15 (2018). doi: <a href="https://doi.org/10.1186/s13059-017-1382-0">10.1186/s13059-017-1382-0</a></li>',
        '<li>10x Genomics Space Ranger 2.1.0 [Online]: <a href="https://www.10xgenomics.com/support/software/space-ranger">10xgenomics.com/support/software/space-ranger</a></li>',
        '<li>Marconato L, Palla G, Yamauchi K, Virshup I, Heidari E, Treis T, Toth M, Shrestha R, Vöhringer H, Huber W, Gerstung M, Moore J, Theis F, Stegle O. SpatialData: an open and universal data framework for spatial omics. bioRxiv 2023.05.05.539647; doi:<a href="https://doi.org/10.1101/2023.05.05.539647"> 10.1101/2023.05.05.539647</a></li>',
    ].join(' ').trim()

    return reference_text
}

def methodsDescriptionText(mqc_methods_yaml) {
    // Convert  to a named map so can be used as with familiar NXF ${workflow} variable syntax in the MultiQC YML file
    def meta = [:]
    meta.workflow = workflow.toMap()
    meta["manifest_map"] = workflow.manifest.toMap()

    // Pipeline DOI
    if (meta.manifest_map.doi) {
        // Using a loop to handle multiple DOIs
        // Removing `https://doi.org/` to handle pipelines using DOIs vs DOI resolvers
        // Removing ` ` since the manifest.doi is a string and not a proper list
        def temp_doi_ref = ""
        def manifest_doi = meta.manifest_map.doi.tokenize(",")
        manifest_doi.each { doi_ref ->
            temp_doi_ref += "(doi: <a href=\'https://doi.org/${doi_ref.replace("https://doi.org/", "").replace(" ", "")}\'>${doi_ref.replace("https://doi.org/", "").replace(" ", "")}</a>), "
        }
        meta["doi_text"] = temp_doi_ref.substring(0, temp_doi_ref.length() - 2)
    }
    else {
        meta["doi_text"] = ""
    }
    meta["nodoi_text"] = meta.manifest_map.doi ? "" : "<li>If available, make sure to update the text to include the Zenodo DOI of version of the pipeline used. </li>"

    // Tool references
    meta["tool_citations"] = toolCitationText().replaceAll(", \\.", ".").replaceAll("\\. \\.", ".").replaceAll(", \\.", ".")
    meta["tool_bibliography"] = toolBibliographyText()


    def methods_text = mqc_methods_yaml.text

    def engine = new groovy.text.SimpleTemplateEngine()
    def description_html = engine.createTemplate(methods_text).make(meta)

    return description_html.toString()
}

// dfp/ffp must be given for every cycle of a sample or none; a mix silently misaligns
// profiles against images in Ashlar. JSON Schema cannot check across rows.
def validateIlluminationColumns(rows) {
    rows.groupBy { it[0].id }.each { sample, cycles ->
        def withProfiles = cycles.count { it[2] && it[3] }
        assert withProfiles == 0 || withProfiles == cycles.size() : (
            "Sample '${sample}': dfp and ffp must be given for every cycle or for none. " +
            "Found ${withProfiles} of ${cycles.size()} cycles with profiles. " +
            "Supplying them for some cycles only would misalign illumination profiles against images."
        )
    }
    return rows
}

// cycle_number must run 1..N per sample. Repeats give two cycles the same meta (the BaSiCPy
// join key), so profiles attach by completion order. Gaps usually mean a missing cycle.
def validateCycleNumbers(rows) {
    rows.groupBy { it[0].id }.each { sample, cycles ->
        def numbers = cycles.collect { it[0].cycle_number }.sort()
        def expected = (1..numbers.size()).toList()

        def repeated = numbers.countBy { it }.findAll { _n, count -> count > 1 }.keySet().sort()
        assert !repeated : (
            "Sample '${sample}': cycle_number is repeated: ${repeated}. Cycles are identified " +
            "by sample and cycle_number together, so two rows sharing both are the same cycle " +
            "as far as the pipeline can tell, and each cycle's illumination profile would be " +
            "attached to whichever image finished first. Number the cycles 1..${numbers.size()}."
        )

        assert numbers == expected : (
            "Sample '${sample}': cycle_number must run 1..${numbers.size()} without gaps. " +
            "Got ${numbers}. A gap usually means a cycle is missing from the samplesheet, and " +
            "the pipeline would process the rest without remarking on it."
        )
    }
    return rows
}

// marker_sheet repeats on every cycle row of a sample; all copies must agree.
def validateMarkerSheetColumn(rows) {
    rows.groupBy { it[0].id }.each { sample, cycles ->
        def sheets = cycles.collect { it[4] as String }.unique()
        assert sheets.size() == 1 : (
            "Sample '${sample}': every cycle must name the same marker_sheet. Found " +
            "${sheets.size()}: ${sheets}. The marker sheet describes the whole stitched " +
            "image rather than one cycle of it, so a sample can only have one."
        )
    }
    return rows
}

// Sample name to marker sheet. Relies on validateMarkerSheetColumn having run.
def markerSheetsBySample(rows) {
    return rows.collectEntries { row -> [(row[0].id): row[4]] }
}

// Marker sheet checks that JSON Schema cannot express.
def validateMarkersheet(rows, sample = null) {
    def where = sample ? "marker_sheet for sample '${sample}'" : "marker_sheet"
    // channel_number is continuous across cycles; restarting per cycle mislabels later channels.
    def numbers = rows.collect { it.channel_number }
    def expected = (1..rows.size()).toList()
    assert numbers == expected : (
        "${where}: channel_number must run 1..${rows.size()} continuously across all cycles, " +
        "without restarting per cycle. Got ${numbers}."
    )

    // Unique marker names: they become feature columns, and roleByName below (collectEntries)
    // would silently keep only the last role of a duplicate. Also saves a full stitch.
    def duplicateNames = rows
        .groupBy { it.marker_name }
        .findAll { _name, group -> group.size() > 1 }
        .keySet()
        .sort()
    assert !duplicateNames : (
        "${where}: marker_name must be unique. Repeated: ${duplicateNames}. Marker names " +
        "become the feature matrix column names, so a duplicate makes a column ambiguous."
    )

    // Every cycle needs a dna channel: registration, segmentation and the photobleaching metric use it.
    def cyclesWithoutDna = rows
        .groupBy { it.cycle_number }
        .findAll { _cycle, channels -> !channels.any { it.channel_role == 'dna' } }
        .keySet()
        .sort()
    assert !cyclesWithoutDna : (
        "${where}: every cycle needs at least one channel with channel_role 'dna'. " +
        "Missing for cycle(s): ${cyclesWithoutDna}. Registration, segmentation and the " +
        "cross-cycle photobleaching check all read the nuclear stain."
    )

    // A background channel must have role autofluorescence. Checked even without backsub,
    // since QC reads channel_role too.
    def roleByName = rows.collectEntries { [(it.marker_name): it.channel_role] }
    def wrongRole = rows
        .findAll { it.background && roleByName[it.background] != 'autofluorescence' }
        .collect { "${it.marker_name} -> ${it.background} (role: ${roleByName[it.background] ?: 'no such channel'})" }
    assert !wrongRole : (
        "${where}: background must name a channel whose channel_role is " +
        "'autofluorescence'. Offending rows: ${wrongRole}"
    )

    // backsub needs exposure and a valid background; otherwise it fails confusingly inside the tool.
    if (params.use_backsub) {
        def noExposure = rows.findAll { !it.exposure }.collect { it.marker_name }
        assert !noExposure : (
            "${where}: use_backsub is enabled, so every channel needs an exposure. " +
            "Missing for: ${noExposure}"
        )

        def names = rows.collect { it.marker_name } as Set
        def unknown = rows.findAll { it.background && !(it.background in names) }
            .collect { "${it.marker_name} -> ${it.background}" }
        assert !unknown : (
            "${where}: background must name another channel's marker_name. Unknown: ${unknown}"
        )

        // Removing extra dna channels is common; removing all of them fails late, in QC_IMAGES.
        assert rows.any { it.channel_role == 'dna' && !it.remove } : (
            "${where}: use_backsub is enabled, so remove drops channels, and every 'dna' " +
            "channel is marked remove. Keep at least one 'dna' channel without remove: " +
            "segmentation and QC read the nuclear stain after removal."
        )

        // Segmentation runs after backsub, so a removed channel is no longer in the image.
        def removed = rows.findAll { it.remove }.collect { it.marker_name } as Set
        ['cellpose_channels', 'stardist_channels'].each { param ->
            def value = params[param]
            if (!(value instanceof CharSequence)) {
                return
            }
            // Same split as getChannels (modules/local/utils.nf).
            def gone = value.toString().split(/[ ,|]+/).findAll { it in removed }
            assert !gone : (
                "${where}: ${param} names channel(s) marked remove: ${gone}. With use_backsub, " +
                "removed channels are dropped before segmentation."
            )
        }
    }
    else {
        def ignored = rows.findAll { it.remove }.collect { it.marker_name }
        if (ignored) {
            log.warn(
                "${where}: remove has no effect without use_backsub; these channels are kept: ${ignored}"
            )
        }
    }

    return rows
}

// Element at a Python-style index (-1 is the last), or null when out of range.
def atIndex(list, index) {
    return index < list.size() && index >= -list.size() ? list[index] : null
}

// Integer value of the first matching flag in a CLI string (`-c 1`, `-c1`, `--channel=1`), else null.
def flagValue(args, flags) {
    def tokens = (args ?: '').tokenize(' ')
    return tokens.indexed().findResult { i, t ->
        def value = null
        if (t in flags) {
            value = i + 1 < tokens.size() ? tokens[i + 1] : null
        }
        else {
            def flag = flags.find { f -> t.startsWith("${f}=") || (f.size() == 2 && t.startsWith(f) && t.size() > 2) }
            value = flag ? t.substring(flag.size()).replaceFirst('^=', '') : null
        }
        value?.isInteger() ? value.toInteger() : null
    }
}

// Ashlar and Coreograph take the nuclear channel by index from *_args, not from the sheet.
// A non-dna channel there registers or dearrays on a marker without any error, so stop.
def checkReferenceChannels(rows, sample = null) {
    def where = sample ? "Sample '${sample}'" : "marker_sheet"
    def problems = []

    // Ashlar applies one within-cycle index (default 0, -1 for the last) to every cycle.
    def align = flagValue(params.ashlar_args, ['-c', '--align-channel']) ?: 0
    def offCycles = rows.groupBy { it.cycle_number }.sort().findResults { cycle, channels ->
        def ch = atIndex(channels.sort(false) { it.channel_number }, align)
        ch?.channel_role == 'dna' ? null : "cycle ${cycle}: ${ch ? "${ch.marker_name} (${ch.channel_role})" : 'no such channel'}"
    }
    if (offCycles) {
        problems << (
            "Ashlar aligns every cycle on within-cycle channel index ${align} (ashlar_args -c, " +
            "default 0), which is not a dna channel in ${offCycles.join('; ')}. Put the nuclear " +
            "stain at the same position in every cycle, or set -c."
        )
    }

    // Coreograph reads one index (default 0, -1 for the last) of the stitched image, all channels.
    if (params.use_tma_dearray) {
        def index = flagValue(params.coreograph_args, ['--channel']) ?: 0
        def ch = atIndex(rows.sort(false) { it.channel_number }, index)
        if (ch?.channel_role != 'dna') {
            problems << (
                "Coreograph dearrays on channel index ${index} (coreograph_args --channel, default 0), " +
                "which is ${ch ? "${ch.marker_name} (${ch.channel_role})" : 'not in the sheet'}, not a " +
                "dna channel. Set --channel to a dna channel_number minus 1."
            )
        }
    }

    problems.each { problem ->
        if (params.skip_reference_dna_check) {
            log.warn("${where}: ${problem} Continuing because skip_reference_dna_check is set.")
        }
    }
    // A plain boolean, so the assert does not repeat the message in its value dump.
    def ok = params.skip_reference_dna_check || !problems
    assert ok : (
        "${where}: ${problems.join(' ')} If this is intended, set skip_reference_dna_check: true."
    )
    return rows
}

// Every parameter in nextflow_schema.json (top level and $defs groups), as name to definition.
def schemaParams() {
    def schema = new groovy.json.JsonSlurper().parseText(
        file("${projectDir}/nextflow_schema.json").text
    )
    def declared = [:]
    declared.putAll(schema.properties ?: [:])
    (schema['$defs'] ?: [:]).each { _group, body ->
        declared.putAll(body.properties ?: [:])
    }
    return declared
}

// Rejects `--flag false` for booleans: Nextflow sets the bare flag to true and drops the value,
// which survives only in workflow.commandLine. `--flag true` is rejected too, for consistency.
def rejectSpacedBooleans(command_line) {
    if (!command_line) {
        return command_line
    }

    def booleans = schemaParams().findAll { _name, definition -> definition.type == 'boolean' }.keySet()

    // Tokenised, not regex: the pair arrives quoted (`'--use_qc false'`) and interpolated
    // slashy patterns fail under the Nextflow 26 parser.
    def tokens = command_line.replace("'", " ").replace('"', " ").tokenize(" ")

    def offenders = []
    tokens.eachWithIndex { token, i ->
        if (!token.startsWith("--")) {
            return
        }
        def name = token.substring(2)
        // Next token starting with `-` means a bare flag. `--x=false` is left to rejectStringBooleans.
        if (name in booleans && i + 1 < tokens.size() && !tokens[i + 1].startsWith("-")) {
            offenders << "  --${name} ${tokens[i + 1]}"
        }
    }
    offenders = offenders.sort()

    if (!offenders) {
        return command_line
    }

    error(
        "Boolean parameter(s) written with a space:\n${offenders.join('\n')}\n\n" +
        "Nextflow reads the flag on its own and throws the value away, so each of these " +
        "is enabled regardless of what follows it. The value never reaches the pipeline, " +
        "which is why this has to be caught here rather than checked after the fact.\n\n" +
        "Use a params file, where the value is a real boolean:\n\n" +
        "    nextflow run . -params-file params.yml\n\n" +
        "To switch a boolean on, a bare flag is enough: `--use_cellpose`."
    )
}

// Rejects `--flag=false`: the string "false" is truthy in Groovy, and params ignores writes to
// keys already set, so it cannot be coerced. A bare flag arrives as "true" and is allowed.
def rejectStringBooleans(params) {
    def declared = schemaParams()
    def offenders = declared
        .findAll { name, definition ->
            definition.type == 'boolean' &&
                params.containsKey(name) &&
                params[name] instanceof CharSequence &&
                params[name].toString().toLowerCase() != 'true'
        }
        .collect { name, _definition -> "  --${name}=${params[name]}" }
        .sort()

    if (!offenders) {
        return params
    }

    error(
        "Boolean parameter(s) given as text on the command line:\n${offenders.join('\n')}\n\n" +
        "Nextflow passes these through as strings, and every non-empty string is true in " +
        "Groovy, so the pipeline would read each of these as enabled and do the opposite " +
        "of what was asked while reporting success. The value cannot be corrected here " +
        "because a parameter already set on the command line is not writable. Use a " +
        "params file instead, where `false` is a real boolean:\n\n" +
        "    nextflow run . -params-file params.yml\n\n" +
        "To switch a boolean on, a bare flag works: `--use_cellpose`."
    )
}

// Rejects params the schema does not declare, which would otherwise be silently ignored.
// TODO: replace with nf-schema's validation.failUnrecognisedParams once it stops throwing (broken up to 2.8.0).
def rejectUnknownParams(params) {
    def declared = schemaParams().keySet()

    // Set by tooling, not users. A missing entry aborts every nf-test pipeline run.
    def injected = [
        'nf_test_output',  // nf-test
        // tests/nextflow.config, for the nf-core module tests
        'modules_testdata_base_path',
    ] as Set

    def unknown = (params.keySet() - declared - injected).sort()
    if (!unknown) {
        return params
    }

    // Substring match catches doubled prefixes such as `use_use_tma_dearray`.
    def hints = unknown.collectEntries { name ->
        def near = declared.findAll { d -> d != name && (d.contains(name) || name.contains(d)) }.sort()
        [(name): near]
    }

    def lines = unknown.collect { name ->
        hints[name] ? "  ${name}  (did you mean: ${hints[name].join(', ')}?)" : "  ${name}"
    }

    error(
        "Unrecognised parameter(s):\n${lines.join('\n')}\n\n" +
        "Every parameter must be declared in nextflow_schema.json. A parameter that is " +
        "not declared is silently ignored, so a run configured with a misspelt switch " +
        "does the opposite of what was asked and still reports success. Run with --help " +
        "to list the parameters this pipeline accepts."
    )
}

def validateParams(params) {
    if (params.containsKey("read")) {
        error("You use a deprecated Sopa params format. We flattened all parameters to conform to the future nextflow 26.04 strict syntax check.\nSee the nf-core/sopa docs for more details on the new syntax usage: https://nf-co.re/sopa/docs/usage/.")
    }

    def STAINING_BASED_METHODS = ['use_stardist', 'use_cellpose']
    def enabled = STAINING_BASED_METHODS.count { params[it] }

    // Exactly one backend: with none, ch_resolved is unassigned and AGGREGATE fails obscurely.
    assert enabled <= 1 : "Only one of ${STAINING_BASED_METHODS} may be used, but ${enabled} are enabled"
    assert enabled >= 1 : "A segmentation backend is required: set one of ${STAINING_BASED_METHODS} to true, " +
        "or use a profile that does (for example -profile test)"

    // Dearraying (preprocessing only) sets meta.slide, which MERGE_SPATIALDATA groups on;
    // without it every core shares a null key and unrelated slides merge.
    assert !(params.use_tma_dearray && !params.use_preprocessing) :
        "use_tma_dearray requires use_preprocessing. Dearraying is part of the preprocessing " +
        "half; to re-enter already-dearrayed cores, list them in the samplesheet with " +
        "use_preprocessing = false and use_tma_dearray = false."

    return params
}
