from tempfile import NamedTemporaryFile

import requests
from PIL import Image
from disclosure_extractor import (
    process_financial_document,
    process_judicial_watch,
    print_results,
)
from flask import Flask, request, jsonify

from src.utils.audio import convert_mp3
from src.utils.financial_disclosures import query_thumbs_db, download_images
from src.utils.tasks import (
    extract_from_docx,
    extract_from_doc,
    extract_from_wpd,
    extract_from_html,
    extract_from_txt,
    make_pdftotext_process,
    extract_from_pdf,
    rasterize_pdf,
    make_png_thumbnail_for_instance,
    get_page_count,
    make_pdf_from_image_array,
    strip_metadata,
)

app = Flask(__name__)


@app.route("/")
def heartbeat():
    """Heartbeat

    :return: success response
    :type: dict
    """
    return jsonify({"success": True, "msg": "Docker container running."})


@app.route("/extract_doc_content", methods=["POST"])
def extract_content():
    """Extract txt from different document types.

    :return: The content of a document/error message.
    :type: json object
    """

    f = request.files["file"]
    do_ocr = request.args.get("do_ocr", default=False)
    if do_ocr == "True":
        do_ocr = True

    extension = f.filename.split(".")[-1]
    with NamedTemporaryFile(suffix=".%s" % extension) as tmp:
        f.save(tmp.name)
        if extension == "pdf":
            content, err, returncode = make_pdftotext_process(tmp.name)
            if do_ocr and len(content.strip()) == 0:
                with NamedTemporaryFile(suffix=".tiff") as tmp_tiff:
                    _, _, _ = rasterize_pdf(tmp.name, tmp_tiff.name)
                    content, err, returncode = extract_from_pdf(tmp_tiff)
                    if content == "":
                        content, err, returncode = (
                            "",
                            "Unable to extract document content",
                            1,
                        )
            else:
                if len(content.strip()) == 0:
                    content, err, returncode = "", "No content detected", 1
        elif extension == "doc":
            content, err, returncode = extract_from_doc(tmp.name)
        elif extension == "docx":
            content, err, returncode = extract_from_docx(tmp.name)
        elif extension == "html":
            content, err, returncode = extract_from_html(tmp.name)
        elif extension == "txt":
            content, err, returncode = extract_from_txt(tmp.name)
        elif extension == "wpd":
            content, err, returncode = extract_from_wpd(tmp.name)
        else:
            content = ""
            err = "Unable to extract content due to unknown extension"
            returncode = 1
        return jsonify(
            {
                "content": content,
                "err": str(err),
                "error_code": str(returncode),
            }
        )


@app.route("/convert_audio_file", methods=["POST"])
def convert_audio_file():
    """Convert an audio file to MP3 and return it

    :return: MP3 audio file
    :type: HTTPS response
    """
    f = request.files["file"]
    with NamedTemporaryFile() as tmp:
        f.save(tmp.name)
        audio_file, err, error_code = convert_mp3(tmp.name)
        response = {
            "content": str(audio_file),
            "error_code": error_code,
            "err": err,
        }
        return jsonify(response)


@app.route("/make_png_thumbnail", methods=["POST"])
def make_png_thumbnail():
    """Make a thumbail of the first page of a PDF and return it.

    :return: A response containing our file and any errors
    :type: HTTPS response
    """
    f = request.files["file"]
    max_dimension = int(request.args.get("max_dimension"))
    with NamedTemporaryFile(suffix=".%s" % "pdf") as tmp:
        f.save(tmp.name)
        thumbnail, err, error_code = make_png_thumbnail_for_instance(
            tmp.name, max_dimension
        )
        response = {
            "content": str(thumbnail),
            "error_code": error_code,
            "err": err,
        }
        return jsonify(response)


@app.route("/get_page_count", methods=["POST"])
def pg_count():
    """Get page count form PDF

    :return:
    """
    f = request.files["file"]
    extension = f.filename.split(".")[-1]
    with NamedTemporaryFile(suffix=".%s" % extension) as tmp:
        f.save(tmp.name)
        content, err, error_code = get_page_count(tmp.name, extension)
        return jsonify(
            {"pg_count": content, "err": err, "error_code": error_code}
        )


@app.route("/make_pdftotext_process", methods=["POST"])
def pdf_to_text():
    """Extract text from text based PDFs immediately.

    :return:
    """
    f = request.files["file"]
    extension = f.filename.split(".")[-1]
    with NamedTemporaryFile(suffix=".%s" % extension) as tmp:
        f.save(tmp.name)
        content, err = make_pdftotext_process(tmp.name)
        return jsonify({"content": content, "err": err})


# ------- Financial Disclosure Microservice requests ------- #
@app.route("/financial_disclosure/single_image", methods=["POST"])
def generate_pdf_from_image_url():
    """Take a single image tiff and convert it into a multipage PDF.

    Download a single image and split it into its component pages.
    :param aws_url: URL of image file we want to process
    :type aws_url: str
    :return: PDF
    """
    error_code = 0
    err = ""
    url = request.args.get("url")
    try:
        img = Image.open(requests.get(url, stream=True).raw)
    except TimeoutError:
        err = "Timeout occurred"
    width, height = img.size
    image_list = []
    i, page_width, page_height = 0, width, (1046 * (float(width) / 792))
    while i < (height / page_height):
        image = img.crop(
            (0, (i * page_height), page_width, (i + 1) * page_height)
        )
        image_list.append(image)
        i += 1
    pdf_bytes = make_pdf_from_image_array(image_list)
    clean_pdf = strip_metadata(pdf_bytes)
    response = {
        "content": str(clean_pdf),
        "err": err,
        "error_code": error_code,
    }
    return jsonify(response)


@app.route("/financial_disclosure/multi_image", methods=["POST"])
def make_pdf_from_images():
    """Query, download and combine multiple images into a PDF

    :return: PDF
    """
    err = ""
    error_code = 0
    clean_pdf = ""
    lookup = ""
    try:
        aws_path = request.args.get("aws_path")
        sorted_urls, lookup = query_thumbs_db(aws_path)
        image_list = download_images(sorted_urls)
        pdf_content = make_pdf_from_image_array(image_list)
        clean_pdf = strip_metadata(pdf_content)
    except TimeoutError:
        err = "Timeout Error"
        error_code = 1
    except Exception as e:
        err = str(e)
        error_code = 1

    response = {
        "content": str(clean_pdf),
        "err": err,
        "lookup": lookup,
        "error_code": error_code,
    }
    return jsonify(response)


@app.route("/financial_disclosure/extract", methods=["POST"])
def financial_disclosure_extract():
    """Extract content from a financial disclosure.

    :return:
    """
    url = request.args.get("url")
    file = request.files.get("file", None)
    if url is not None:
        pdf = requests.get(url, timeout=60 * 10).content
    elif file is not None:
        pdf = file.read()
    else:
        return jsonify({"err": "No file posted"})

    fd = process_financial_document(pdf_bytes=pdf, show_logs=True)
    if fd["success"] is True:
        print_results(fd)
    return jsonify(fd)


@app.route("/financial_disclosure/jw_extract", methods=["POST"])
def judical_watch_extract():
    """Extract content from an older JW financial disclosure.

    :return: Disclosure information
    """
    url = request.args.get("url")
    file = request.files.get("file", None)
    if url is not None:
        pdf = requests.get(url, timeout=60 * 10).content
    elif file is not None:
        pdf = file.read()
    else:
        return jsonify({"err": "No file posted"})
    fd = process_judicial_watch(pdf_bytes=pdf, show_logs=True)
    if fd["success"] is True:
        print_results(fd)

    return jsonify(fd)


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
