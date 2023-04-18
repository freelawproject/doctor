
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

Magic:

 - The mimetype of the file will be determined by the name of the file you pass in. For example, if you pass in medical_assessment.pdf, the `pdf` extractor will be used.

Valid requests will receive a JSON response with the following keys:

 - `content`: The utf-8 encoded text of the file
 - `err`: An error message, if one should occur.
 - `extension`: The sniffed extension of the file.
 - `extracted_by_ocr`: Whether OCR was needed and used during processing.
 - `page_count`: The number of pages, if it applies.


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

The "error" field is set if there was an issue processing the PDF.

If "results" is empty there were no bad redactions found

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

This isn't the cleanest of CURLs because we have to convert the large JSON file to a query string, but for proof of concept here is the result

    curl 'http://localhost:5050/convert/audio/mp3/?audio_data=%7B%22court_full_name%22%3A+%22Testing+Supreme+Court%22%2C+%22court_short_name%22%3A+%22Testing+Supreme+Court%22%2C+%22court_pk%22%3A+%22test%22%2C+%22court_url%22%3A+%22http%3A%2F%2Fwww.example.com%2F%22%2C+%22docket_number%22%3A+%22docket+number+1+005%22%2C+%22date_argued%22%3A+%222020-01-01%22%2C+%22date_argued_year%22%3A+%222020%22%2C+%22case_name%22%3A+%22SEC+v.+Frank+J.+Custable%2C+Jr.%22%2C+%22case_name_full%22%3A+%22case+name+full%22%2C+%22case_name_short%22%3A+%22short%22%2C+%22download_url%22%3A+%22http%3A%2F%2Fmedia.ca7.uscourts.gov%2Fsound%2Fexternal%2Fgw.15-1442.15-1442_07_08_2015.mp3%22%7D' \
     -X 'POST' \
     -F "file=@doctor/test_assets/1.wma"

This returns the audio file as a file response.


## Testing

Testing is designed to be run with the `docker-compose.dev.yml` file.  To see more about testing
checkout the DEVELOPING.md file.

## Sentry Logging

For debugging purposes, it's possible to set your Sentry DSN to send events to Sentry.
By default, no SENTRY_DSN is set and no events will be sent to Sentry.
To use Sentry set the SENTRY_DSN environment variable to your DSN. Using Docker you can set it with:

    docker run -d -p 5050:5050 -e SENTRY_DSN=<https://yout-sentry-dsn> freelawproject/doctor:latest
