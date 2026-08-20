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
        // cast_cli_params. Without this, --expand_radius_ratio 0.1 arrives as the
        // string "0.1" and fails schema validation against a number, and likewise
        // --use_cellpose true against a boolean. Anything set on the command line
        // rather than in a profile or params file needs coercion.
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
    //
    // The samplesheet has two shapes, chosen by params.use_preprocessing:
    //
    //   true  (default) one row per acquisition cycle. Raw tiles go through
    //                   illumination correction and stitching first.
    //   false           one row per sample, pointing at data already in a form
    //                   sopa can read. Used for pre-stitched images, for dearrayed
    //                   TMA cores re-entering the pipeline, and for toy_dataset.
    //
    // Declared out here because the marker sheet block further down needs it as well,
    // and a `def` inside an if block is scoped to that block.
    def cycle_rows = null

    if (params.use_preprocessing) {
        // Rows arrive as [meta, image_tiles, dfp, ffp, marker_sheet], in schema
        // property order. Read once and used twice: for the cycles themselves, and
        // for the per-sample marker sheets below.
        cycle_rows = validateMarkerSheetColumn(
            validateIlluminationColumns(
                samplesheetToList(params.input, "${projectDir}/assets/schema_input_cycle.json")
            )
        )

        Channel
            .fromList(cycle_rows)
            .map { meta, image_tiles, dfp, ffp, _marker_sheet ->
                // sdata_dir is deliberately not set here. It is per-sample, and at
                // this point a row is one cycle of a sample. It is added after
                // cycles are grouped and stitched.
                //
                // marker_sheet is dropped here rather than carried through
                // stitching. It is per-sample and every cycle of a sample repeats
                // the same value, so carrying it per cycle would mean grouping it
                // back again and choosing which copy to trust.
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

    //
    // Sopa params validation
    //
    rejectSpacedBooleans(workflow.commandLine)
    rejectStringBooleans(params)
    rejectUnknownParams(params)
    validateParams(params)

    //
    // Marker sheets, one per sample. One row per channel across all cycles.
    //
    // The sheet is a samplesheet column rather than a parameter because it
    // describes a sample, and two samples in one run may have different channel
    // layouts. A parameter could only ever say one thing for all of them.
    //
    // Checked once per sample, so a sheet shared by several samples is parsed once for
    // each of them. That is deliberate rather than merely tolerable: the checks are
    // cheap on a file this size, and validating per sample is what lets the error
    // message name the sample whose sheet is wrong.
    //
    // The channel carries the path rather than the parsed rows. Every consumer reads
    // the CSV itself: set_channel_names.py and qc_metrics.py both parse with
    // csv.DictReader and require only the columns they use, and backsub reads it with
    // pd.read_csv and passes unknown columns through to its own marker output. So
    // nothing needs the sheet rewritten, and a path joins onto an image by key while
    // a list of rows would have to be broadcast.
    //
    // Validated synchronously, before any channel exists. An assert thrown inside a
    // channel operator is swallowed and the run dies with no message; called here it
    // surfaces the way validateIlluminationColumns does.
    if (params.use_preprocessing) {
        def sheets_by_sample = markerSheetsBySample(cycle_rows)

        // Every column of the marker sheet is declared as meta, so each row arrives
        // as a single-element list holding the meta map, hence it[0].
        sheets_by_sample.each { sample, sheet ->
            validateMarkersheet(
                samplesheetToList(sheet, "${projectDir}/assets/schema_marker.json").collect { it[0] },
                sample,
            )
        }

        ch_markersheet = channel.fromList(
            sheets_by_sample.collect { sample, sheet -> [[id: sample], file(sheet)] }
        )
    }
    else {
        // No marker sheet on this path, and none needed. An image entering the
        // pipeline pre-stitched is assumed to carry its own channel names, so nothing
        // downstream renames them.
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

//
// Illumination profiles are all-or-nothing per sample.
//
// Whether BaSiCPy runs is inferred from the samplesheet rather than set by a
// parameter, which is only safe if the columns are consistent. A samplesheet
// giving dfp and ffp for some cycles of a sample but not others would send half
// the cycles down each path, and Ashlar would receive profiles that do not line
// up with its images. That is silent misregistration, the same failure mode as
// unsorted cycles. JSON Schema cannot express this, so it is checked here.
//
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

//
// The marker sheet is per sample, but the samplesheet has one row per cycle, so the
// column repeats. All copies must agree.
//
// A sample whose cycles name different sheets is asking for one image to be described
// two ways, and whichever copy happened to be read first would win silently. JSON
// Schema validates rows independently and cannot see across them, so this is checked
// here, the same category and the same reason as validateIlluminationColumns.
//
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

//
// Sample name to marker sheet, one entry per sample.
//
// Distinct by construction, because validateMarkerSheetColumn has already established
// that a sample's cycles agree. Two samples may share a sheet, and then it is parsed
// once per sample; the sheets are small and the checks are cheap.
//
def markerSheetsBySample(rows) {
    return rows.collectEntries { row -> [(row[0].id): row[4]] }
}

//
// Marker sheet checks that JSON Schema cannot express.
//
def validateMarkersheet(rows, sample = null) {
    def where = sample ? "marker_sheet for sample '${sample}'" : "marker_sheet"
    // channel_number is a continuous index across all cycles, not per-cycle. If it
    // restarts each cycle, every channel after cycle 1 is mislabelled and the
    // feature table silently carries the wrong marker names.
    def numbers = rows.collect { it.channel_number }
    def expected = (1..rows.size()).toList()
    assert numbers == expected : (
        "${where}: channel_number must run 1..${rows.size()} continuously across all cycles, " +
        "without restarting per cycle. Got ${numbers}."
    )

    // Marker names must be unique. They become the column names of the feature matrix,
    // so duplicates make it ambiguous, and backsub requires uniqueness too.
    //
    // set_channel_names.py already rejects them, but it runs after Ashlar and backsub,
    // so a duplicate costs a full stitch before anything complains. Checked here it
    // costs nothing. The role lookup below is the more immediate reason: it is built
    // with collectEntries, which keeps the last value for a repeated key, so a name
    // appearing twice with different roles would silently resolve to one of them and
    // the background check would then pass or fail for a reason nobody could see.
    def duplicateNames = rows
        .groupBy { it.marker_name }
        .findAll { _name, group -> group.size() > 1 }
        .keySet()
        .sort()
    assert !duplicateNames : (
        "${where}: marker_name must be unique. Repeated: ${duplicateNames}. Marker names " +
        "become the feature matrix column names, so a duplicate makes a column ambiguous."
    )

    // Every cycle needs a nuclear stain. Ashlar registers cycles against one another
    // through it, segmentation reads it, and the cross-cycle photobleaching metric
    // compares it from cycle to cycle. A cycle without one is either a sheet that
    // forgot to label it or an acquisition that nothing downstream can align.
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

    // The background column names the channel to subtract, so whatever it names is by
    // definition an autofluorescence channel. Two columns describing one fact would
    // otherwise be free to disagree, and the disagreement would be invisible.
    //
    // Checked whether or not backsub runs. A sheet that labels its background channel
    // as a marker is describing the acquisition wrongly, and that description is what
    // QC and every later feature reads, not just backsub. This also catches a
    // background naming a channel that does not exist when backsub is off, which the
    // check below only catches when it is on.
    def roleByName = rows.collectEntries { [(it.marker_name): it.channel_role] }
    def wrongRole = rows
        .findAll { it.background && roleByName[it.background] != 'autofluorescence' }
        .collect { "${it.marker_name} -> ${it.background} (role: ${roleByName[it.background] ?: 'no such channel'})" }
    assert !wrongRole : (
        "${where}: background must name a channel whose channel_role is " +
        "'autofluorescence'. Offending rows: ${wrongRole}"
    )

    // Background subtraction scales by exposure and looks up a background channel
    // by marker_name. Both are optional columns in general but mandatory here, and
    // a missing one produces a confusing failure inside the tool.
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
    }

    return rows
}

//
// Every parameter the schema declares, as name to definition.
//
// Read from nextflow_schema.json so the schema stays the single source of truth: a new
// parameter is declared once and every check here picks it up without a second edit.
// Parameters live in the $defs groups, with a handful at the top level.
//
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

//
// A boolean written with a space is destroyed before the pipeline can see the value.
//
// `--use_qc false` does not leave QC enabled through string truthiness, which is what it
// looks like. Nextflow reads `--use_qc` as a bare flag, sets it to boolean true, and
// discards the `false` entirely: it is not in params, and it is not in the positional
// args either. So the run explicitly enables the step the user asked to switch off, and
// by the time any code runs, `params.use_qc` is indistinguishable from the default.
//
// workflow.commandLine is the only place the value survives, which is why this reads a
// string rather than inspecting params. Taken as an argument rather than read from the
// global so the check can be tested.
//
// `--use_qc true` is rejected too. It happens to produce the right answer, for the same
// reason `--use_qc false` produces the wrong one, and a form that works for one value
// and silently inverts the other is worse than one that never works.
//
def rejectSpacedBooleans(command_line) {
    if (!command_line) {
        return command_line
    }

    def booleans = schemaParams().findAll { _name, definition -> definition.type == 'boolean' }.keySet()

    // Tokenised rather than matched with a regex, because the command line arrives with
    // the offending pair quoted as `'--use_qc false'` and because an interpolated slashy
    // pattern does not survive the Nextflow 26 parser. Quotes become separators, and
    // tokenize discards the empties that leaves behind.
    def tokens = command_line.replace("'", " ").replace('"', " ").tokenize(" ")

    def offenders = []
    tokens.eachWithIndex { token, i ->
        if (!token.startsWith("--")) {
            return
        }
        def name = token.substring(2)
        // A following token starting with `-` is the next option, so the flag was bare
        // and nothing was swallowed. `--use_qc=false` is a single token and is not
        // matched here; rejectStringBooleans catches that form.
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

//
// A boolean given as a string is a boolean that will be read the wrong way round.
//
// `--use_qc=false` reaches the pipeline as the string "false", and every non-empty
// string is true in Groovy, so `if (params.use_qc)` takes the enabled branch. This
// affects every boolean the pipeline declares, not one of them.
//
// It cannot be fixed by coercing the value. params is a ScriptBinding$ParamsMap, which
// ignores writes to a key that is already set: both `params.use_qc = false` and
// `params.putAll([use_qc: false])` return without error and change nothing. Verified on
// Nextflow 26.04.6. So the only honest options are to fail or to read the value through
// a helper at every use site, and failing once at startup beats a helper that someone
// eventually forgets.
//
// A bare `--use_qc` also arrives as a string, "true", and that one is both idiomatic and
// correct, so only strings that do not mean true are rejected.
//
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

//
// Reject parameters the schema does not declare.
//
// `use_use_tma_dearray = true` reached a real run: pipeline_info/params_*.json from
// the published WSI run records both the typo and the real parameter, with
// validate_params true. The typo was accepted, silently ignored, and the run did the
// opposite of what it asked for while reporting success.
//
// nf-schema is supposed to do this. `validation.failUnrecognisedParams` is documented
// and its value is read, but the field it assigns to is never declared on
// ValidationConfig, so setting the option aborts the run with
// `MissingPropertyException: No such property: failUnrecognisedParams`. Checked
// against the source at tags 2.7.2, 2.7.3 and 2.8.0, which is every release at the
// time of writing, and there is no upstream issue for it. Delete this function and
// set the option once that is fixed.
//
// Unknown samplesheet columns need nothing here: `additionalProperties: false` in the
// sheet schemas already rejects them, which is what `validation.failUnrecognisedHeaders`
// would otherwise have been for.
//
def rejectUnknownParams(params) {
    def declared = schemaParams().keySet()

    // Set by the tooling rather than by a user, so absent from the schema by design.
    def injected = [
        'nf_test_output',  // nf-test, which is also in nf-schema's own default ignore list
    ] as Set

    def unknown = (params.keySet() - declared - injected).sort()
    if (!unknown) {
        return params
    }

    // A doubled prefix is the typo that got through, and `use_use_tma_dearray`
    // contains `use_tma_dearray`, so plain containment finds it. Cheap, and it never
    // claims a match it cannot show.
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

    // Exactly one segmentation backend must be enabled. Both default to false, so
    // running without a profile would otherwise leave ch_resolved unassigned and
    // fail deep inside AGGREGATE with an unhelpful Groovy error.
    assert enabled <= 1 : "Only one of ${STAINING_BASED_METHODS} may be used, but ${enabled} are enabled"
    assert enabled >= 1 : "A segmentation backend is required: set one of ${STAINING_BASED_METHODS} to true, " +
        "or use a profile that does (for example -profile test)"

    // TMA dearray happens inside the preprocessing half, and it is what stamps
    // meta.slide onto each core. MERGE_SPATIALDATA groups on meta.slide, so
    // without preprocessing every core would group under a null key and silently
    // merge unrelated slides into one object.
    assert !(params.use_tma_dearray && !params.use_preprocessing) :
        "use_tma_dearray requires use_preprocessing. Dearraying is part of the preprocessing " +
        "half; to re-enter already-dearrayed cores, list them in the samplesheet with " +
        "use_preprocessing = false and use_tma_dearray = false."

    return params
}
