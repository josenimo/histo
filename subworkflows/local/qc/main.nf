//
// Quality control: metrics, images and the report that renders both.
//
// Three processes rather than one, because they are three different kinds of work.
// QC_METRICS is a streamed pass over the pixels, seconds to a minute, and produces the
// machine-readable numbers. QC_IMAGES builds a neighbour graph over every cell and
// rasterises polygons, which takes minutes and needs scanpy. QC_REPORT reads their
// output and writes HTML using nothing but the standard library. Splitting them means
// each gets its own resource request, the fast numbers do not wait on the slow
// pictures, and a failure in the clustering still leaves a report with the metrics in
// it.
//
// The metrics JSON is the contract. It is published alongside the HTML precisely so
// that an unattended run has something to act on: the report is for a person, and a
// pass-or-fail gate will read the JSON.
//

include { QC_METRICS } from '../../../modules/local/qc_metrics'
include { QC_IMAGES  } from '../../../modules/local/qc_images'
include { QC_REPORT  } from '../../../modules/local/qc_report'

workflow QC {
    take:
    ch_sdata         // channel: [ val(meta), path(sdata) ]
    ch_markers       // channel: path(csv), or an empty channel
    ch_unsubtracted  // channel: [ val(meta), path(tif) ], or an empty channel

    main:

    def ch_versions = channel.empty()

    // One marker sheet serves every sample, so it has to reach the process as a value
    // channel. As a queue channel holding one item, Nextflow pairs it element-wise
    // against the stores and stops at the shorter one: a dearrayed slide with four cores
    // produced exactly one report and no error. `.first()` makes it a value channel so
    // it is broadcast instead, which is the same reason PREPROCESS_IMAGES calls
    // `.first()` on its own markerout.
    //
    // ifEmpty([]) covers the pre-stitched path, where preprocessing never ran and
    // nothing describes the channels; [] collapses to no --markers flag in the module.
    def markers = ch_markers.ifEmpty([]).first()

    // join() on meta pairs each store with its own pre-subtraction image. remainder
    // keeps stores that have no match, which is every store when backsub did not run
    // or the slide was dearrayed, and fills the missing side with null -> [].
    def ch_metrics_input = ch_sdata
        .join(ch_unsubtracted, remainder: true)
        .map { meta, sdata, tif -> [meta, sdata, tif ?: []] }
        .filter { _meta, sdata, _tif -> sdata }

    QC_METRICS(ch_metrics_input, markers)
    ch_versions = ch_versions.mix(QC_METRICS.out.versions)

    if (params.use_qc_images) {
        QC_IMAGES(ch_sdata, markers)
        ch_versions = ch_versions.mix(QC_IMAGES.out.versions)
        ch_report_input = QC_METRICS.out.metrics.join(QC_IMAGES.out.images)
    }
    else {
        ch_report_input = QC_METRICS.out.metrics.map { meta, metrics -> [meta, metrics, []] }
    }

    QC_REPORT(ch_report_input)
    ch_versions = ch_versions.mix(QC_REPORT.out.versions)

    emit:
    metrics  = QC_METRICS.out.metrics  // channel: [ val(meta), path(json) ] the machine-readable contract
    report   = QC_REPORT.out.report    // channel: [ val(meta), path(html) ]
    versions = ch_versions             // channel: [ path(versions.yml) ]
}
