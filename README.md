
Courtlistener Binary, Transformers and Extractors
------------------------------------

## Notes

This is a microservice of containing Binaries, Transformers and Extractors
used by Courtlistener.com.  

The goal of this microservice is to isolate out these tools to let Courtlistener (a django site)
be streamlined and easier to maintain.  This service is setup to run with NGINX and gunicorn with a
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

    docker-compose -f docker-compose.yml up --build -d

This will expose the endpoints on port 5050, which can be modified in the `nginx/nginx.conf` file and points
to the django server running on port 8000.

For more options and configuration of nginx checkout [https://nginx.org/en/docs/](https://nginx.org/en/docs/).

After the compose file has finished you should be able to test that you have a working environment by running

    curl 0.0.0.0:5050
    curl http://localhost:5050

which should return a JSON response.

    {"success": true, "msg": "Heartbeat detected."}

if you are using the development docker-compose file the via the docker network you would use
container name instead of localhost or 0.0.0.0.  In this instance you would use:

    curl http://bte:5050

Additionally, the corresponding python-ic command would look like something like this:

    import requests
    response = requests.get('http://0.0.0.0:5050', timeout=2)

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
     -F "file=@bte/test_assets/image-pdf.pdf"

##### Endpoint: /extract/doc/text/

This is an important endpoint. Given a document it will extract out the text and return a page count (if possible)
along with general metadata used in CL.

    curl 'http://localhost:5050/extract/doc/text/' \
     -X 'POST' \
     -F "file=@bte/test_assets/vector-pdf.pdf"

or if you need to OCR the document you pass in the ocr_available parameter.

    curl 'http://localhost:5050/extract/doc/text/?ocr_available=True' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"

Presuming that the request was valid you should receive the following JSON response back.

    {
        "content": content,
        "err": str(err),
        "extracted_by_ocr": extracted_by_ocr,
        "error_code": str(returncode),
        "page_count": page_count,
        "success": True if returncode == 0 else False,
    }

The method accepts **PDF** (image and vector), **DOC, DOCX, HTML, TXT and WPD** files.

## Utilities

#### Endpoint: /utils/page-count/pdf/

This method takes a document and returns the page count.

    curl 'http://localhost:5050/utils/page-count/pdf/' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"

This will return an HTTP response with page count.  In the above example it would return __2__.

#### Endpoint: /utils/mime-type/

This method takes a document and returns the mime type.

    curl 'http://localhost:5050/utils/mime-type/?mime=False' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"

returns as JSON response identifying the document type

    {"mimetype": "PDF document, version 1.3"}

and

    curl 'http://localhost:5050/utils/mime-type/?mime=True' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"

returns as JSON response identifying the document type

    {"mimetype": "application/pdf"}

Another example  

    curl 'http://localhost:5050/utils/mime-type/?mime=True' \
     -X 'POST' \
     -F "file=@bte/test_assets/word-doc.doc"

returns

    {"mimetype": "application/msword"}

This method is useful for identifying the type of document, incorrect documents and weird documents.

## Converters

#### Endpoint: /convert/image/pdf/

Given an image or indeterminate length, this endpoint will convert it to a pdf.

    curl 'http://localhost:5050/convert/image/pdf/' \
     -X 'POST' \
     -F "file=@bte/test_assets/long-image.tiff" \
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
     -F "file=@bte/test_assets/image-pdf.pdf"
     -o test-thumbnail.png

This returns the binary data of the thumbnail.

Keep in mind that this curl will also write the file to the current directory.

#### Endpoint: /convert/audio/mp3/

This endpoint takes an audio file and converts it to an MP3 file.  This is used to convert different audio formats
from courts across the country and standardizes the format for our end users.  

This endpoint also adds the SEAL of the court to the MP3 file and updates the metadata to reflect our updates.

This isn't the cleanest of CURLs because we have to convert the large JSON file to a query string, but for proof of concept here is the result

    curl 'http://localhost:5050/convert/audio/mp3/?audio_data=%7B%22court_full_name%22%3A+%22Testing+Supreme+Court%22%2C+%22court_short_name%22%3A+%22Testing+Supreme+Court%22%2C+%22court_pk%22%3A+%22test%22%2C+%22court_url%22%3A+%22http%3A%2F%2Fwww.example.com%2F%22%2C+%22docket_number%22%3A+%22docket+number+1+005%22%2C+%22date_argued%22%3A+%222020-01-01%22%2C+%22date_argued_year%22%3A+%222020%22%2C+%22case_name%22%3A+%22SEC+v.+Frank+J.+Custable%2C+Jr.%22%2C+%22case_name_full%22%3A+%22case+name+full%22%2C+%22case_name_short%22%3A+%22short%22%2C+%22download_url%22%3A+%22http%3A%2F%2Fmedia.ca7.uscourts.gov%2Fsound%2Fexternal%2Fgw.15-1442.15-1442_07_08_2015.mp3%22%7D' \
     -X 'POST' \
     -F "file=@bte/test_assets/1.wma"

This returns the audio file back as a JSON Response which can be written to an MP3 file.

    {
      "audio_b64": audio_b64,
      "duration": audio_file.info.time_secs,
      "success": True,
    }


Nginx
-----

NGINX controls a lot of what is occurring and currently has some limitations that can be adjusted
Currently the maximum file size that can be buffered is 100 MB.  One could modify NGINX by modifying `nginx/nginx.conf` file.


## Testing

Testing is designed to be run with the `docker-compose.dev.yml` file.  To see more about testing
checkout the DEVELOPING.md file.
