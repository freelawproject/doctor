from tempfile import NamedTemporaryFile

from flask import Flask, request, send_file, jsonify

from src.utils.audio import convert_mp3
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
)

app = Flask(__name__)


@app.route("/")
def heartbeat():
    """Heartbeat

    :return: success response
    :type: dict
    """
    return {"success": True, "msg": "Docker container running."}


@app.route("/extract_doc_content", methods=["POST"])
def extract_content():
    """Pass documents to extract content

    :return: Content of documents
    :type: str
    """

    f = request.files["file"]
    do_ocr = request.args.get("do_ocr", default=False)
    if do_ocr == "True":
        do_ocr = True

    extension = f.filename.split(".")[-1]
    with NamedTemporaryFile(suffix=".%s" % extension) as tmp:
        f.save(tmp.name)
        if extension == "pdf":
            content, err = make_pdftotext_process(tmp.name)
            if do_ocr and len(content.strip()) == 0:
                with NamedTemporaryFile(suffix=".tiff") as tmp_tiff:
                    _, _, _ = rasterize_pdf(tmp.name, tmp_tiff.name)
                    content, err = extract_from_pdf(tmp_tiff)
                    if content == "":
                        content, err = (
                            "Unable to extract document content.",
                            "Failure",
                        )
            else:
                if len(content.strip()) == 0:
                    content, err = "", "Failure"
            return jsonify({"content": content, "err": "err"})
        elif extension == "doc":
            content, err = extract_from_doc(tmp.name)
        elif extension == "docx":
            content, err = extract_from_docx(tmp.name)
        elif extension == "html":
            content, err = extract_from_html(tmp.name)
        elif extension == "txt":
            content, err = extract_from_txt(tmp.name)
        elif extension == "wpd":
            content, err = extract_from_wpd(tmp.name)
        else:
            print(
                "*****Unable to extract content due to unknown extension: %s "
                "on opinion: %s****" % (extension, "opinion_pk")
            )
            return
        return jsonify({"content": content, "err": err})


@app.route("/convert_audio_file", methods=["POST"])
def convert_audio_file():
    f = request.files["file"]
    with NamedTemporaryFile() as tmp:
        f.save(tmp.name)
        converted_file = convert_mp3(tmp.name)
        return send_file(converted_file)


@app.route("/make_png_thumbnail", methods=["POST"])
def make_png_thumbnail():
    f = request.files["file"]
    max_dimension = request.args.get("max_dimension")
    extension = f.filename.split(".")[-1]
    with NamedTemporaryFile(suffix=".%s" % extension) as tmp:
        f.save(tmp.name)
        return make_png_thumbnail_for_instance(tmp.name, max_dimension)


@app.route("/get_page_count", methods=["POST"])
def pg_count():
    f = request.files["file"]
    extension = f.filename.split(".")[-1]
    with NamedTemporaryFile(suffix=".%s" % extension) as tmp:
        f.save(tmp.name)
        return jsonify({"pg_count": get_page_count(tmp.name, extension)})


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
        return jsonify({"content": content, "success": err})


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
