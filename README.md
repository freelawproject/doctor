
Doctor
------------------------------------

Welcome to Doctor, Free Law Project's microservice for converting, extracting and modifying documents and audio files.

At a high level, this service provides you with high-performance HTTP endpoints that can:

 - Extract text from various types of documents
 - Convert audio files from one format to another while stripping messy metadata
 - Create thumbnails of PDFs
 - Provide metadata about PDFs

Under the hood, Doctor uses gunicorn to connect to a django service. The django service uses
carefully configured implementations of `ffmpeg`, `pdftotext`, `tesseract`, `ghostscript`, and a
number of other converters.


Quick Start
-----------

Assuming you have docker installed run:

    docker run -d -p 5050:5050 freelawproject/doctor:latest

This will expose the endpoints on port 5050 with one gunicorn worker. This is usually ideal because it allows you to horizontally scale Doctor using an orchestration system like Kubernetes.

If you are not using a system that supports horizontal scaling, you may wish to have more gunicorn workers so that Doctor can handle more simultaneous tasks. To set that up, simply set the DOCTOR_WORKERS environment variable:

    docker run -d -p 5050:5050 -e DOCTOR_WORKERS=16 freelawproject/doctor:latest

If you are doing OCR or audio conversion, scaling through a system like Kubernetes or through by giving Doctor many workers becomes particularly important. If it does not have a worker available, your call to Doctor will probably time out.

After the image is running, you should be able to test that you have a working environment by running

    curl http://localhost:5050

which should return a text response:

    Heartbeat detected.


ENDPOINTS
-------------

## Overview

The service currently supports the following tools:

1. Extract text from PDF, RTF, DOC, DOCX, or WPD, HTML, TXT files.
1. OCR text from a scanned PDF.
1. Get page count for a PDF document.
1. Check for bad redactions in a PDF document.
1. Convert audio files from wma, ogg, wav to MP3.
1. Create a thumbnail of the first page of a PDF (for use in Open Graph tags)
1. Convert an image or images to a PDF.
1. Identify the mime type of a file.


A brief description and curl command for each endpoint is provided below.

## Extractors

### Endpoint: /extract/doc/text/

Given a document, extract out the text and assorted metadata. Supports the following document types:

 - `pdf` - Adobe portable document format files, via `pdftotext`.
 - `doc` - Word document files, via `antiword`.
 - `docx` - Open Office XML files, via `docx2txt`.
 - `html` - HTML files, via `lxml.html.clean.Cleaner`. Strips out dangerous tags and hoists their contents to their parent. Hoisted tags include: `a`, `body`, `font`, `noscript`, and `img`.
 - `txt` - Text files. This attempts to normalize all encoding questions to utf-8. First, we try cp1251, then utf-8, ignoring errors.
 - `wpd` - Word Perfect files, via `wpd2html` followed by cleaning the HTML as above.

```bash
curl 'http://localhost:5050/extract/doc/text/' \
  -X 'POST' \
  -F "file=@doctor/test_assets/vector-pdf.pdf"
```

Parameters:

 - `ocr_available`: Whether doctor should use tesseract to provide OCR services for the document. OCR is always possible in doctor, but sometimes you won't want to use it, since it can be slow. If you want it disabled for this request, omit this optional parameter. To enable it, set ocr_available to `True`:

```bash
curl 'http://localhost:5050/extract/doc/text/?ocr_available=True' \
  -X 'POST' \
  -F "file=@doctor/test_assets/image-pdf.pdf"
```

OCR renders and reads the PDF in slices of `DOCTOR_OCR_PAGES_PER_SLICE`
pages (default 25), one slice at a time, so a request's peak memory and
`/tmp` usage are set by the slice size rather than by the document's page
count. Lower it if pods with several concurrent OCR requests run out of
memory; raise it to spend fewer ghostscript and tesseract invocations on
large documents. The extracted text is the same whatever the value.

Magic:

 - The mimetype of the file will be determined by the name of the file you pass in. For example, if you pass in medical_assessment.pdf, the `pdf` extractor will be used.

Valid requests will receive a JSON response with the following keys:

 - `content`: The utf-8 encoded text of the file
 - `err`: An error message, if one should occur.
 - `extension`: The sniffed extension of the file.
 - `extracted_by_ocr`: Whether OCR was needed and used during processing.
 - `page_count`: The number of pages, if it applies.

### Endpoint: /extract/recap/text/

Given a RECAP pdf, extract out the text using PDF Plumber, OCR or a combination of the two

Parameters:

 - `strip_margin`: Whether doctor should crop the edges of the recap document during processing. With PDF plumber it will ignore traditional 1 inch margin.  With an OCR it lowers the threshold for hiding OCR gibberish. To enable it, set strip_margin to `True`:

```bash
curl 'http://localhost:5050/extract/recap/text/?strip_margin=True' \
  -X 'POST' \
  -F "file=@doctor/recap_extract/gov.uscourts.cacd.652774.40.0.pdf"
```

Valid requests will receive a JSON response with the following keys:

 - `content`: The utf-8 encoded text of the file
 - `extracted_by_ocr`: Whether OCR was needed and used during processing.


### Endpoint: /extract/opinion/structured/

Given a **digital** (text-based) court PDF and the court it came from, extract a
structured opinion with [centralia][centralia]. For the courts centralia has
been ported to this replaces pdftotext/OCR: instead of one flat string you get
the case-level criteria, one entry per writing with its own author and text, and
Harvard casebody XML. The payload is passed through exactly as centralia returns
it — nothing is composed or re-stitched here.

[centralia]: https://github.com/freelawproject/centralia

Parameters:

 - `court_id` (required): The CourtListener court id, e.g. `ca1`. It is required
   rather than sniffed, because centralia reads only the courts it has a reader
   for, and an unregistered id would otherwise silently read worse.
 - `allow_pending` (optional): Read a court that is still being worked on.
   Without it, a held-back court is refused; `diagnostics.rollout` reports
   which you got.

```bash
curl 'http://localhost:5050/extract/opinion/structured/' \
  -X 'POST' \
  -F "file=@doctor/test_assets/ca1-opinion.pdf" \
  -F 'court_id=ca1'
```

Valid requests receive a JSON response with `success: true` plus centralia's
payload. The keys callers use most:

 - `status`: `valid` | `review` | `scanned` | `failed`
 - `cluster`: the case — case name, citation, docket number, filing dates (both
   as printed and ISO), panel, parties, disposition, lower court
 - `opinions`: one entry per writing, each with `type`, `author`, `author_name`,
   `text`, `html` and `footnotes`. Footnote text is **already inside** the
   writing's `text`; callers do not append it.
 - `headmatter` / `endmatter`: the cover and the appearances, as role-bearing
   rows, each with its own `footnotes`
 - `html`: the document's text as HTML; `casebody`: Harvard casebody XML
 - `diagnostics`: page facts, what went unplaced, and `warnings`

Note that `status` alone is not an OCR-fallback signal: an image-based PDF can
come back `valid` with zero opinions and no text. Callers should fall back to
`/extract/doc/text/` when the returned text is empty.

Failures return `{"success": false, "error_code": ..., "msg": ...}`. The error
codes are `VALIDATION_FAILED`, `UNKNOWN_COURT` (no court declares that id),
`COURT_NOT_RELEASED` (the court is still being worked on; pass `allow_pending`)
and `EXTRACTION_FAILED`. As with `/convert/pdf/bitonal/`, `msg` is a **string**
for every code except `VALIDATION_FAILED`, where it is the **object** Django's
form validation produces (field name to a list of `{message, code}`), so a
caller reading `msg` should expect either shape.


## Utilities

### Endpoint: /utils/page-count/pdf/

This method takes a document and returns the page count.

    curl 'http://localhost:5050/utils/page-count/pdf/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf"

This will return an HTTP response with page count.  In the above example it would return __2__.

### Endpoint: /utils/check-redactions/pdf/

This method takes a document and returns the bounding boxes of bad
redactions as well as any discovered text.

    curl 'http://localhost:5050/utils/check-redactions/pdf/' \
	  -X 'POST' \
	  -F "file=@doctor/test_assets/x-ray/rectangles_yes.pdf"

returns as JSON response with bounding box(es) and text recovered.
```
{
  "error": false,
  "results": {
    "1": [
      {
        "bbox": [
          412.54998779296875,
          480.6099853515625,
          437.8699951171875,
          494.39996337890625
        ],
        "text": "“No”"
      },
      {
        "bbox": [
          273.3500061035156,
          315,
          536.8599853515625,
          328.79998779296875
        ],
        "text": "“Yes”, but did not disclose all relevant medical history"
      },
      {
        "bbox": [
          141.22999572753906,
          232.20001220703125,
          166.54998779296875,
          246
        ],
        "text": "“No”"
      }
    ]
  }
}
```

The "error" field is set if there was an issue processing the PDF.

If "results" is empty there were no bad redactions found otherwise it
is a list of bounding box along with the text recovered.

See: https://github.com/freelawproject/x-ray/#readme

### Endpoint: /utils/mime-type/

This method takes a document and returns the mime type.

    curl 'http://localhost:5050/utils/mime-type/?mime=False' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf"

returns as JSON response identifying the document type

    {"mimetype": "PDF document, version 1.3"}

and

    curl 'http://localhost:5050/utils/mime-type/?mime=True' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf"

returns as JSON response identifying the document type

    {"mimetype": "application/pdf"}

Another example  

    curl 'http://localhost:5050/utils/mime-type/?mime=True' \
     -X 'POST' \
     -F "file=@doctor/test_assets/word-doc.doc"

returns

    {"mimetype": "application/msword"}

This method is useful for identifying the type of document, incorrect documents and weird documents.

### Endpoint: /utils/add/text/pdf/

This method will take an image PDF and return the PDF with transparent text overlayed on the document.
This allows users to copy and paste (more or less) from our OCRd text.

    curl 'http://localhost:5050/utils/add/text/pdf/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf" \
     -o image-pdf-with-embedded-text.pdf

### Endpoint: /utils/audio/duration/

This endpoint returns the duration of an MP3 file.

    curl 'http://localhost:5050/utils/audio/duration/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/1.mp3"

### Endpoint: /utils/document-number/pdf/

This method takes a document from the federal filing system and returns its document entry number.

    curl 'http://localhost:5050/utils/document-number/pdf/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/recap_documents/ca2_1-1.pdf"

This will return an HTTP response with the document number.  In the above example it would return __1-1__.


## Converters

### Endpoint: /convert/image/pdf/

Given an image of indeterminate length, this endpoint will convert it to a pdf with reasonable page breaks. This is meant for extremely long images that represent multi-page documents, but can be used to convert a smaller image to a one-page PDF.

    curl 'http://localhost:5050/convert/image/pdf/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/long-image.tiff" \
      --output test-image-to-pdf.pdf

Keep in mind that this curl will write the file to the current directory.

### Endpoint: /convert/images/pdf/

Given a list of urls for images, this endpoint will convert them to a pdf. This can be used to convert multiple images to a multi-page PDF. We use this to convert financial disclosure images to simple PDFs.

    curl 'http://localhost:5050/convert/images/pdf/?sorted_urls=%5B%22https%3A%2F%2Fcom-courtlistener-storage.s3-us-west-2.amazonaws.com%2Ffinancial-disclosures%2F2011%2FA-E%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11_Page_1.tiff%22%2C+%22https%3A%2F%2Fcom-courtlistener-storage.s3-us-west-2.amazonaws.com%2Ffinancial-disclosures%2F2011%2FA-E%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11_Page_2.tiff%22%5D' \
        -X POST \
        -o image.pdf

This returns the binary data of the pdf.


### Endpoint: /convert/pdf/bitonal/

Converts a scanned PDF (or a page range of it) to a bitonal (1-bit, CCITT
Group 4) PDF. Pages are rasterized to grayscale one at a time, thresholded,
and re-embedded as raw G4 streams, so memory use stays flat regardless of
document size. Each output page keeps the exact MediaBox of its source page,
so detection boxes expressed relative to the page rect stay valid.

Parameters:

 - `dpi` (default 300, range 72-600): rasterization resolution.
 - `threshold` (default 128, range 0-255): gray values above it become white.
 - `first_page` / `last_page` (optional, 1-indexed, inclusive): page range.
 - `page_timeout` (default 120, max 200) / `total_timeout` (default 1800,
   max 1800): seconds one page, and the whole conversion, may take. Both
   default to the settings below, which are also their ceilings; above a
   ceiling is `VALIDATION_FAILED`.
 - `input_url` (instead of a `file` upload): a presigned GET URL to fetch the
   input from.
 - `output_url` (optional): a presigned PUT URL. When given, the result is
   uploaded there (Content-Type `application/pdf` must be part of the
   signature) and the response is a JSON summary instead of the PDF itself.

With a file upload, the PDF comes back inline:

    curl 'http://localhost:5050/convert/pdf/bitonal/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf" \
     -F 'dpi=300' \
     -F 'threshold=128' \
     -o bitonal.pdf

With presigned URLs, doctor never needs storage credentials — it only ever
sees the URLs:

    curl 'http://localhost:5050/convert/pdf/bitonal/' \
     -X 'POST' \
     --data-urlencode "input_url=$PRESIGNED_GET" \
     --data-urlencode "output_url=$PRESIGNED_PUT"

which returns a summary like:

    {"success": true, "pages": 200, "page_count": 200, "dpi": 300,
     "threshold": 128, "first_page": 1, "last_page": 200,
     "bytes": 14680064, "sha256": "...", "source_sha256": "...",
     "duration_ms": 61200}

Failures return `{"success": false, "error_code": ..., "msg": ...}`. The
error codes are: `VALIDATION_FAILED`, `INVALID_PDF`, `PAGE_RANGE_INVALID`,
`CONVERSION_FAILED`, `CONVERSION_TIMEOUT`, `PAGE_COUNT_MISMATCH`,
`PAGE_GEOMETRY_MISMATCH`, `EGRESS_BLOCKED`, `INPUT_TOO_LARGE`,
`INPUT_DOWNLOAD_FAILED`, `INPUT_URL_EXPIRED`, `RESULT_UPLOAD_FAILED`,
`RESULT_URL_EXPIRED` and `INTERNAL_ERROR`. The `*_EXPIRED` codes mean a
presigned signature returned HTTP 403, so the caller must re-presign rather
than retry the same URL. Transient transport failures are retried with
backoff before failing; a malformed URL is never retried and fails as
`INPUT_DOWNLOAD_FAILED` or `RESULT_UPLOAD_FAILED`.
`INTERNAL_ERROR` means doctor itself failed unexpectedly — unlike
`CONVERSION_FAILED`, the same request may succeed on retry.
`CONVERSION_TIMEOUT` means a page, or the whole conversion, ran out of time;
like `INTERNAL_ERROR`, and unlike `CONVERSION_FAILED`, it may succeed on
retry. A failure on a page also reports `page_number`, `pages_completed`,
`elapsed_ms`, `pixels` (the page at the requested dpi) and, for a timeout,
`timeout_limit` (`page` or `total`, whichever limit was nearer) as their own
JSON fields, so no caller has to parse the message text.

A single PUT is atomic on S3: the result object existing implies all of its
bytes are there, so `head_object` on the (caller-chosen) result key is a
reliable completion probe. Note the upload happens while the request stays
open; the HTTP response is the status channel.

The `DOCTOR_EGRESS_ALLOWED_HOSTS` environment variable (comma-separated
fnmatch patterns) restricts which hosts `input_url` and `output_url` may
point to; allowed URLs must also be https. It defaults to
`*.amazonaws.com`, which accepts presigned S3 URLs while blocking
cluster-internal targets. Deployments can tighten it to exact bucket
hostnames (a pattern without wildcards is an exact match), and setting it
empty disables the check entirely, which local development and the test
suite rely on (see `.env.example`).

Four more environment variables bound the resources one request can
consume. `DOCTOR_BITONAL_PAGE_TIMEOUT_SECONDS` (default 120) limits a
single page's `pdftoppm` call and `DOCTOR_BITONAL_PAGE_TIMEOUT_MAX_SECONDS`
(default 200) caps what `page_timeout` may raise it to;
`DOCTOR_BITONAL_TIMEOUT_SECONDS` (default 1800) is the whole-conversion
budget and its own ceiling; `DOCTOR_BITONAL_MAX_DOWNLOAD_BYTES`
(default 1 GiB, 0 disables) caps how large an `input_url` download may be
(`INPUT_TOO_LARGE`). The defaults carry 30-60x headroom over the designed
workload (a 200-page shard converts in about a minute), so they only trip
on stuck or runaway work.

### Endpoint: /convert/pdf/thumbnail/

Thumbnail takes a pdf and returns a png thumbnail of the first page.

    curl 'http://localhost:5050/convert/pdf/thumbnail/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf" \
     -o test-thumbnail.png

This returns the binary data of the thumbnail.

Keep in mind that this curl will also write the file to the current directory.

### Endpoint: /convert/pdf/thumbnails/

Given a PDF and a range or pages, this endpoint will return a zip file containing thumbnails
for each page requested. This endpoint also takes an optional parameter called max_dimension,
this property scales the long side of each thumbnail (width for landscape pages, height for
portrait pages) to fit in the specified number of pixels.

For example if you want thumbnails for the first four pages:

    curl 'http://localhost:5050/convert/pdf/thumbnails/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/vector-pdf.pdf" \
     -F 'pages="[1,2,3,4]"' \
     -F 'max_dimension=350' \
     -o thumbnails.zip

This will return four thumbnails in a zip file.

### Endpoint: /convert/audio/mp3/

This endpoint takes an audio file and converts it to an MP3 file.  This is used to convert different audio formats
from courts across the country and standardizes the format for our end users.  

This endpoint also adds the SEAL of the court to the MP3 file and updates the metadata to reflect our updates.

    curl 'http://localhost:5050/convert/audio/mp3/?audio_data=%7B%22court_full_name%22%3A+%22Testing+Supreme+Court%22%2C+%22court_short_name%22%3A+%22Testing+Supreme+Court%22%2C+%22court_pk%22%3A+%22test%22%2C+%22court_url%22%3A+%22http%3A%2F%2Fwww.example.com%2F%22%2C+%22docket_number%22%3A+%22docket+number+1+005%22%2C+%22date_argued%22%3A+%222020-01-01%22%2C+%22date_argued_year%22%3A+%222020%22%2C+%22case_name%22%3A+%22SEC+v.+Frank+J.+Custable%2C+Jr.%22%2C+%22case_name_full%22%3A+%22case+name+full%22%2C+%22case_name_short%22%3A+%22short%22%2C+%22download_url%22%3A+%22http%3A%2F%2Fmedia.ca7.uscourts.gov%2Fsound%2Fexternal%2Fgw.15-1442.15-1442_07_08_2015.mp3%22%7D' \
     -X 'POST' \
     -F "file=@doctor/test_assets/1.wma"

This returns the audio file as a file response.

### Endpoint: /convert/audio/ogg/

This endpoint takes an audio file and converts it to an OGG file. The conversion process downsizes files by using
a single audio channel and fixing the sampling rate to 8 kHz.

This endpoint also optimizes the output for voice over IP applications.

    curl 'http://localhost:5050/convert/audio/ogg/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/1.wma"

This returns the audio file as a file response.


## Testing

Testing is designed to be run with the `compose.yaml` file.  To see more about testing
checkout the DEVELOPING.md file.

## Sentry Logging

For debugging purposes, it's possible to set your Sentry DSN to send events to Sentry.
By default, no SENTRY_DSN is set and no events will be sent to Sentry.
To use Sentry set the SENTRY_DSN environment variable to your DSN. Using Docker you can set it with:

    docker run -d -p 5050:5050 -e SENTRY_DSN=<https://yout-sentry-dsn> freelawproject/doctor:latest
