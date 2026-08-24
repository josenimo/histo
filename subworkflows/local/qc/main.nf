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
    ch_markers       // channel: [ val(meta), path(csv) ], or an empty channel
    ch_unsubtracted  // channel: [ val(meta), path(tif) ], or an empty channel

    main:

    def ch_versions = channel.empty()

    // join(..., remainder: true) on meta pairs each store with its own marker sheet and
    // its own pre-subtraction image, and keeps stores that have neither.
    //
    // remainder matters for both. The pre-subtraction image exists only when backsub
    // ran; it is keyed per core on the TMA path, which is why dearraying happens
    // before subtraction rather than after. The marker sheet is absent on the
    // pre-stitched path, where preprocessing never ran and nothing describes the
    // channels. A missing side arrives as null and becomes [], which collapses to no
    // flag at all in the module.
    //
    // This used to be one unkeyed sheet made into a value channel with `.first()` so it
    // could be broadcast. Keyed per sample it is an ordinary join, and the failure that
    // workaround existed to avoid, a four-core slide producing one report, cannot be
    // expressed any more.
    def ch_qc_input = ch_sdata
        .join(ch_unsubtracted, remainder: true)
        .join(ch_markers, remainder: true)
        .map { meta, sdata, tif, markers -> [meta, sdata, tif ?: [], markers ?: []] }
        .filter { _meta, sdata, _tif, _markers -> sdata }

    QC_METRICS(ch_qc_input)
    ch_versions = ch_versions.mix(QC_METRICS.out.versions)

    if (params.use_qc_images) {
        QC_IMAGES(ch_qc_input.map { meta, sdata, _tif, markers -> [meta, sdata, markers] })
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
