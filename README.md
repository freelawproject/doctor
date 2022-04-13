
Doctor
------------------------------------

Welcome to Doctor, Free Law Project's microservice for converting, extracting and modifiying documents.

The goal of this microservice is to isolate out these tools to let Courtlistener (a django site)
be streamlined and easier to maintain.  This service is setup to run with gunicorn with a
series of endpoints that accept JSON, files, and parameters to transform Audio, Documents as well as
extract, modify and replace metadata, text and other data.  

In general, CL houses documents scraped and collected from hundreds of sources and these documents take
many varied formats and versions.

How to Use
----------

This tool is designed to be connected securely from CL via a docker network called cl_net_overlay.  But
it can also be used directly by exposing port 5050.  For more about development of the tool see the
(soon coming) DEVELOPING.md file.


Quick Start
-----------

Assuming you have docker installed run:

    docker run -d -p 5050:5050 freelawproject/doctor:latest

This will expose the endpoints on port 5050 with four gunicorn workers.

If you wish to have more gunicorn workers, you'll want to set the DOCTOR_WORKERS environment variable. You can do that
with:

    docker run -d -p 5050:5050 -e DOCTOR_WORKERS=16 freelawproject/doctor:latest

If you are doing OCR, you will certainly want more workers.

After the image is running, you should be able to test that you have a working environment by running

    curl http://localhost:5050

which should return a text response.

    Heartbeat detected.


ENDPOINTS
-------------

## Overview

The service currently supports the following tools:

1. Convert audio files from wma, ogg, wav to MP3.
2. Convert an image or images to a PDF.
3. Identify the mime type of a file.
4. OCR text from an image PDF.
5. Extract text from PDF, RTF, DOC, DOCX, or WPD, HTML, TXT files.
6. Create a thumbnail of the first page of a PDF.
7. Get page count for a document.

A brief description and curl command for each endpoint is provided below.

## Extractors

##### Endpoint: /extract/pdf/text/

Given a pdf, extract the text from it.  

    curl 'http://localhost:5050/extract/pdf/text/?ocr_available=True' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf"

##### Endpoint: /extract/doc/text/

This is an important endpoint. Given a document it will extract out the text and return a page count (if possible)
along with general metadata used in CL.

    curl 'http://localhost:5050/extract/doc/text/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/vector-pdf.pdf"

or if you need to OCR the document you pass in the ocr_available parameter.

    curl 'http://localhost:5050/extract/doc/text/?ocr_available=True' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf"

Presuming that the request was valid you should receive the following JSON response back.

This returns an JSON Response
And includes the following keys `extracted_by_ocr`, `err`, `page_count`, `content`

The method accepts **PDF** (image and vector), **DOC, DOCX, HTML, TXT and WPD** files.

## Utilities

#### Endpoint: /utils/page-count/pdf/

This method takes a document and returns the page count.

    curl 'http://localhost:5050/utils/page-count/pdf/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf"

This will return an HTTP response with page count.  In the above example it would return __2__.

#### Endpoint: /utils/mime-type/

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

#### Endpoint: /utils/add/text/pdf/

This method will take an image PDF and return the PDF with transparent text overlayed on the document.
This allows users to copy and paste (more or less) from our OCRd text.

    curl 'http://localhost:5050/utils/add/text/pdf/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf" \
     -o image-pdf-with-embedded-text.pdf

#### Endpoint: /utils/audio/duration/

This endpoint returns the duration of an MP3 file.

    curl 'http://localhost:5050/utils/audio/duration/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/1.mp3"

## Converters

#### Endpoint: /convert/image/pdf/

Given an image or indeterminate length, this endpoint will convert it to a pdf.

    curl 'http://localhost:5050/convert/image/pdf/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/long-image.tiff" \
      --output test-image-to-pdf.pdf

Keep in mind that this curl will write the file to the current directory.

#### Endpoint: /convert/images/pdf/

Given a list of urls for images, this endpoint will convert them to a pdf.

    curl 'http://localhost:5050/convert/images/pdf/?sorted_urls=%5B%22https%3A%2F%2Fcom-courtlistener-storage.s3-us-west-2.amazonaws.com%2Ffinancial-disclosures%2F2011%2FA-E%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11_Page_1.tiff%22%2C+%22https%3A%2F%2Fcom-courtlistener-storage.s3-us-west-2.amazonaws.com%2Ffinancial-disclosures%2F2011%2FA-E%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11_Page_2.tiff%22%5D' \
        -X POST \
        -o image.pdf

This returns the binary data of the pdf.

This method is used almost exclusively for financial disclosures.

#### Endpoint: /convert/pdf/thumbnail/

Thumbnail takes a pdf and returns a png thumbnail of the first page.

    curl 'http://localhost:5050/convert/pdf/thumbnail/' \
     -X 'POST' \
     -F "file=@doctor/test_assets/image-pdf.pdf" \
     -o test-thumbnail.png

This returns the binary data of the thumbnail.

Keep in mind that this curl will also write the file to the current directory.

#### Endpoint: /convert/pdf/thumbnails/

Give a PDF and a range or pages, this endpoint will return a zip file containing thumbnails
for each page requested.  For example if you want thumbnails for the first four pages you

    curl 'http://localhost:5050/convert/pdf/thumbnails/?max_dimension=350&pages=%5B1%2C+2%2C+3%2C+4%5D' \
     -X 'POST' \
     -F "file=@doctor/test_assets/vector-pdf.pdf" \
     -o thumbnails.zip

This will return four thumbnails in a zip file.

#### Endpoint: /convert/audio/mp3/

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
