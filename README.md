
Binaries Transformers and Extractors
------------------------------------

This is a microservice of containing Binaries, Transformers and Extractors
used by Courtlistener.com

How to Use
----------

This project is a microservice designed for use by Courtlistener.com.

Hopefully this tool can be used by anyone.  If you are interested in using this tool without Courtlistener you should
start by using the `docker-compose.open.yml`.  This file will expose port 5050
for any application can use to connect to this service.

    docker-compose -f docker-compose.open.yml up --build -d


Quick Start
-----------

Assuming you have docker installed call:

    docker-compose -f docker-compose.yml up --build -d

or

    docker-compose -f docker-compose.dev.yml up --build -d

Depending on your purpose you can either expose the microservice to port
5050 and make a series of requests against it.

In its most basic test the heartbeat microservice can be checked by running

    curl 0.0.0.0:5050

returns

    {"success": true, "msg": "Heartbeat detected."}


NETWORKING
----------

Free Law Project uses this as a microservice that is only accessible from the docket network between
containers.  

ENDPOINTS
---------

Lets do a quick overview of the endpoints in this microservice.

Each endpoint is documented below with curl, but a python requests version can be found in the the tests file.


Audio conversion:
Assuming you are in the root directory the following curl should generate a new MP3 file from the WMA

    curl -X POST -H "Content-Type: application/json" 0.0.0.0:5050/convert-audio -F "file=@/Users/Palin/Code/binaries-transformers-extractors/bte/test_assets/vector-pdf.pdf"  
    curl -X POST 0.0.0.0:5050/pg-count/ -o vector-pdf.pdf -d @/Users/Palin/Code/binaries-transformers-extractors/bte/test_assets/vector-pdf.pdf




So if you wanted to get the page count for a particular PDF document you could accomplish that by running the following CURL command

    curl -i http://0.0.0.0:5050/pg-count/ -X POST -F "file=@bte/test_assets/image-pdf.pdf"

of the equivalent python request

    import requests

    files = {
        'file': ('image-pdf.pdf', open('bte/test_assets/image-pdf.pdf', 'rb')),
    }
    response = requests.post('http://0.0.0.0:5050/pg-count/', files=files)


Extracting text from an regular PDF is also very simple

    curl 'http://0.0.0.0:5050/extract-doc-content/' \
            -X 'POST' \
            -F "file=@bte/test_assets/vector-pdf.pdf"

Extracting text from an image PDF is also very simple

    curl 'http://localhost:5050/extract-doc-content/?ocr_available=2' \
             -X 'POST' \
             -F "file=@bte/test_assets/image-pdf.pdf"


Keep in mind this only works if you uncomment out the port mapping in the docker-compose.yml file.  

This image is by default set up to run over cl_network_overlay - a docker network that allows separate docker containers
to communicate.


#ENDPOINTS

## Extractors

##### Endpoint: /text/

Given a pdf, extract the text from it.  

    curl 'http://localhost:5050/text/?ocr_available=True' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"

##### Endpoint: /extract-doc-content/

This is an important endpoint. Given a document it will extract out the text and return a page count (if possible)
along with general metadata used in CL.

    curl 'http://localhost:5050/extract-doc-content/' \
     -X 'POST' \
     -F "file=@bte/test_assets/vector-pdf.pdf"


    curl 'http://localhost:5050/extract-doc-content/?ocr_available=True' \
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

####Endpoint: /pg-count/

This method takes a document and returns the page count.

    curl 'http://localhost:5050/pg-count/' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"

This will return an HTTP response with page count.  In the above example it would return __2__.

####Endpoint: /mime-type/

This method takes a document and returns the mime type.

    curl 'http://localhost:5050/mime-type/?mime=False' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"

returns as JSON response identifying the document type

    {"mimetype": "PDF document, version 1.3"}

and

    curl 'http://localhost:5050/mime-type/?mime=True' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"

returns as JSON response identifying the document type

    {"mimetype": "application/pdf"}

Another example  

    curl 'http://localhost:5050/mime-type/?mime=True' \
     -X 'POST' \
     -F "file=@bte/test_assets/word-doc.doc"

returns

    {"mimetype": "application/msword"}

This method is useful for identifying the type of document, incorrect documents and weird documents.

## Converters

#### Endpoint: /image-to-pdf/

Given an image or indeterminate length, this endpoint will convert it to a pdf.

    curl 'http://localhost:5050/image-to-pdf/' \
     -X 'POST' \
     -F "file=@bte/test_assets/long-image.tiff" \
      --output test-image-to-pdf.pdf

Keep in mind that this curl will write the file to the current directory.

#### Endpoint: /images-to-pdf/

Given a list of urls for images, this endpoint will convert them to a pdf.

    curl 'http://localhost:5050/images-to-pdf/?sorted_urls=%5B%22https%3A%2F%2Fcom-courtlistener-storage.s3-us-west-2.amazonaws.com%2Ffinancial-disclosures%2F2011%2FA-E%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11_Page_1.tiff%22%2C+%22https%3A%2F%2Fcom-courtlistener-storage.s3-us-west-2.amazonaws.com%2Ffinancial-disclosures%2F2011%2FA-E%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11%2FArmstrong-SB%2520J3.%252009.%2520CAN_R_11_Page_2.tiff%22%5D' \
        -X POST \
        -o image.pdf

This method is used almost exclusively for financial disclosures.


#### Endpoint: /thumbnail/

Thumbnail takes a pdf and returns a png thumbnail of the first page.

    curl 'http://localhost:5050/thumbnail/' \
     -X 'POST' \
     -F "file=@bte/test_assets/image-pdf.pdf"
     -o test-thumbnail.png

Keep in mind that this curl will also write the file to the current directory.


##Audio Converter

#### Endpoint: /convert-audio/

This endpoint takes an audio file and converts it to an MP3 file.  This is used to convert different audio formats
from courts across the country and standardizes the format for our endusers.  

This endpoint also adds the SEAL of the court to the MP3 file and updates the metadata to reflect our updates.

This isnt the cleanest of CURLs becaus we have to convert the large JSON file to a query string, but for proof of concept here is the result

    curl 'http://localhost:5050/convert-audio/?audio_data=%7B%22court_full_name%22%3A+%22Testing+Supreme+Court%22%2C+%22court_short_name%22%3A+%22Testing+Supreme+Court%22%2C+%22court_pk%22%3A+%22test%22%2C+%22court_url%22%3A+%22http%3A%2F%2Fwww.example.com%2F%22%2C+%22docket_number%22%3A+%22docket+number+1+005%22%2C+%22date_argued%22%3A+%222020-01-01%22%2C+%22date_argued_year%22%3A+%222020%22%2C+%22case_name%22%3A+%22SEC+v.+Frank+J.+Custable%2C+Jr.%22%2C+%22case_name_full%22%3A+%22case+name+full%22%2C+%22case_name_short%22%3A+%22short%22%2C+%22download_url%22%3A+%22http%3A%2F%2Fmedia.ca7.uscourts.gov%2Fsound%2Fexternal%2Fgw.15-1442.15-1442_07_08_2015.mp3%22%7D' \
     -X 'POST' \
     -F "file=@bte/test_assets/1.wma"

This returns the audio file back as a JSON Response which can be written to an MP3 file.

    {
      "audio_b64": audio_b64,
      "duration": audio_file.info.time_secs,
      "success": True,
    }


Docker and Nginx
----------------

NGINX controls a lot of what is occurring and currently has some limitations that can be adjusted
Currently the maximum file size that can be buffered is 100 MB.  One could modify NGINX by modifying nginx/nginx.conf file.


Seal Rookery Image
------------

Seal Rookery is a tool that essentailly holds the seals for courts across the country.  It is used by the audio conversion endpoint.


## Testing

Testing is setup with the following default that our tests are run from
a container on the same network as the BTE machine.  This is modeled after
how we plan to use the BTE image for CL.

    docker-compose -f docker-compose.dev.yml up --build -d

Starts the BTE Container and the Mock CL Container that we run our tests from.

    docker exec -it mock_courtlistener python3 -m unittest bte.tests

This is a duplicate of the BTE container, which we use for simplicity, but it
makes the requests across the docker network.


## Building Images

A soon to be written make file will certainly be used to build and push images to docker hub.
