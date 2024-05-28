import re

import pdfplumber
from pdfplumber.ctm import CTM
import pytesseract
from pytesseract import Output
import pandas as pd
from PIL import Image


def deskew(obj: dict) -> bool:
    """Remove skewed text from a page

    CTM stands for current transformation matrix.
    Pdf plumber has a method to calculate the angle of text which we use here

    Traditionally this is only seen in circular stamps which confuses the
    content, or in perpendicular text of the ninth circuit courts which also
    confuses the text.

    :param obj: dictionary from pdfplumber for each word
    :return: if the text should be returned
    """
    if (matrix := obj.get("matrix")) is None:
        return True

    # Remove Skew
    my_char_ctm = CTM(*matrix)
    if my_char_ctm.skew_x != 0:
        return False
    return True


def get_page_text(page: pdfplumber.PDF.pages, strip_margin: bool) -> str:
    """Extract page text

    Using pdf plumber extract out the text of the document that is not
    skewed (ie a stamp of approval) and extract out text removing blue text

    :param page: PdfPlumber page
    :param strip_margin: a flag to crop out the margin of a document and skewed content
    :return: Text from the pdf plumber page
    """
    if strip_margin:
        # Crop margins and remove skewed text
        _, _, width, height = page.bbox
        bbox = (
            (1 / 8.5 * width),
            (1 / 11 * height),
            (7.5 / 8.5 * width),
            (10 / 11 * height),
        )
        doc_text = (
            page.crop(bbox)
            .filter(deskew)
            .extract_text(
                layout=True, keep_blank_chars=True, y_tolerance=5, y_density=25
            )
        )
    else:
        doc_text = page.extract_text(
            layout=True, keep_blank_chars=True, y_tolerance=5, y_density=25
        )
    return doc_text


def page_images(page: pdfplumber.pdf.Page) -> bool:
    """Does the page have images of a certain size

    :param page: pdf plumber
    :return: True if page contains images of a certain size
    """
    for img in page.images:
        if (
            img.get("width") / page.width * img.get("height") / page.height
            > 0.1
        ) or img.get("width") * img.get("width") > 10:
            return True
    return False


def page_annotations(page: pdfplumber.pdf.Page) -> bool:
    """Does the page have annotations which could contain text

    :param page: pdf plumber
    :return: if page has annotations
    """
    if page.annots:
        anno_types = [
            str(annot.get("data").get("Subtype")) for annot in page.annots
        ]
        if "/'FreeText'" in anno_types or "/'Widget'" in anno_types:
            return True
    return False


def adjust_caption_lines(page_text: str) -> str:
    """Adjust the alignment of ) or : or § used to align content

    § is used in texas courts
    : is used in NY courts
    ) is used in many courts

    :param page_text: The text of the first page
    :return: The page text
    """
    for separator in [r"\)", "§", ":"]:
        matches = list(re.finditer(rf"(.* +{separator} .*\n)", page_text))
        central_matches = [
            match
            for match in matches
            if 30 <= match.group().rindex(separator[-1]) <= 70
        ]
        if len(central_matches) < 3:
            continue  # Skip this separator if less than 3 matches found
        # Determine the longest position of the separator
        longest = max(
            match.group().rindex(separator[-1]) for match in central_matches
        )
        adjust = 0
        for match in central_matches:
            match_text = match.group()
            index = match_text.rindex(separator[-1])
            location = match.start() + adjust + index
            # Adjust the page text by adding spaces to align the separators
            page_text = (
                page_text[:location]
                + " " * (longest - index)
                + page_text[location:]
            )
            adjust += longest - index
        return page_text
    return page_text


def page_needs_ocr(page: pdfplumber.pdf.Page, page_text: str) -> bool:
    """Does the page need OCR

    :param page:Pdf Plumber Page
    :param page_text: context extracted from page
    :return: does page need OCR
    """
    if (
        page_text.strip() == ""
        or "(cid:" in page_text
        or page_annotations(page)
        or page_images(page)
        or len(page.curves) > 10
    ):
        return True
    return False


def convert_pdf_page_to_image(
    page: pdfplumber.pdf.Page, strip_margin: bool
) -> Image:
    """Conver page to image and crop margin if applicable

    :param page:Pdf Plumber
    :param strip_margin: bool
    :return: The formatted image
    """
    img = page.to_image(resolution=300)
    _, _, w, h = page.bbox
    width = w * img.scale
    height = h * img.scale

    if strip_margin == True:
        # Because this is OCR - I think its reasonable to crop half the standard
        # 1 inch margin - this leads to much better results and helps reduce
        bbox = (
            (1 / (8.5 * 2) * width),
            (1 / (11 * 2) * height),
            (16 / (8.5 * 2) * width),
            (21 / (11 * 2) * height),
        )
        image = img.original.crop(bbox)
    else:
        image = img.original
    return image


def ocr_image_to_data(image: Image) -> list[pd.DataFrame]:
    """Perform OCR on an image to extract data

    Convert the image of the pdf page to OCR data
    :param image: Pil Image
    :return: A list of DataFrames, each containing OCR data for a block of text
    """
    data_dict = pytesseract.image_to_data(
        image,
        config="-c preserve_interword_spaces=1x1 -c tessedit_do_invert=0 --psm 6 -l eng",
        output_type=Output.DICT,
    )
    df = pd.DataFrame(data_dict)
    filtered_data = df[(df.conf != -1)]
    block_ids = (
        filtered_data.groupby("block_num")
        .first()
        .sort_values("top")
        .index.tolist()
    )
    blocks = [
        filtered_data[filtered_data["block_num"] == block]
        for block in block_ids
    ]
    return blocks


def extract_with_ocr(page: pdfplumber.pdf.Page, strip_margin: bool) -> str:
    """Extract the page using OCR

    :param page:Pdf Plumber Page
    :param strip_margin: If we should trim the margins
    :return: The extracted content for the page
    """

    image = convert_pdf_page_to_image(page, strip_margin)
    data = ocr_image_to_data(image)
    content = ""
    prev = {}
    for words in data:
        for index, word in words.iterrows():
            content = insert_whitespace(content, word, prev)
            content += get_word(word, image.size[0], strip_margin)
            prev = word
    content = cleanup_content(content, page.page_number)
    return content


def insert_whitespace(content: str, word: dict, prev: dict) -> str:
    """Insert whitespace after or before word

    :param content: The text extracted so far
    :param word: The OCR extraction object
    :param prev: The previous word object extracted
    :return: The content with the whitespace appended
    """
    is_new_line = prev.get("line_num", 0) != word["line_num"]
    is_new_par = prev.get("par_num", 0) != word["par_num"]
    prev_end = prev.get("left", 1) + prev.get("width", 1)

    # Add vertical whitespace
    if is_new_line or is_new_par:
        vertical_gap = word["top"] - (
            prev.get("top", 0) + prev.get("height", 0)
        )
        content += "\n\n" if vertical_gap > 100 else "\n"
        prev_end = 0

    # add horizontal whitespace
    content += " " * int(((word["left"] - prev_end) / 25))
    return content


def get_word(word_dict: dict, width: float, strip_margin: bool) -> str:
    """Append word to content

    :param word_dict: the word object from tesseract
    :param width: The width of the document
    :param strip_margin: should we strip the margin
    :return: The text with space
    """
    if strip_margin:
        left_margin = (1 / 8.5) * width
        right_margin = (7.5 / 8.5) * width
    else:
        left_margin = (0.5 / 8.5) * width
        right_margin = (8.0 / 8.5) * width

    word = word_dict["text"]
    conf = word_dict["conf"]
    if word_dict["left"] + word_dict["width"] < left_margin and conf < 40:
        word = " " * len(word)
    elif (conf == 0 and len(word) < 4) or word_dict["left"] == 0:
        word = " " * len(word)
    elif conf < 5 and (len(word) < 4 or len(word) > 20):
        word = "□" * len(word)
    elif conf < 40 and word_dict["left"] > right_margin:
        word = "□" * len(word)

    return f"{word} "


def cleanup_content(content: str, page_number: int) -> str:
    """Reduce legal document line clutter

    Scans containing line numbers or bad scans have pipe issues this simply
    tries to reduce the noise and artifacts and align caption lines
    if easy

    :param content: the page content extracted
    :param page_number: the page number
    :return: the cleaned up text
    """
    if page_number == 1:
        content = adjust_caption_lines(content)

    # remove floating pipes
    pattern = r"\s{4,}\| $"
    # Substitute the matched pipe with an empty string
    content = re.sub(pattern, "", content, flags=re.MULTILINE)

    # remove floating artifacts from the right side
    pattern = r"\s{10,}[a-zA-Z0-9|] $"
    content = re.sub(pattern, "", content, flags=re.MULTILINE)

    content = remove_excess_whitespace(content)
    return f"{content}\n"


def remove_excess_whitespace(document: str) -> str:
    """Remove excess whitespace from OCR

    This function removes empty lines of text at the start and end of a document

    :param document: text of the document
    :return: Document with excess whitespace removed
    """
    m = re.findall(r"(^ +)", document, re.MULTILINE)
    if m:
        shift_left = len(min(m))
        pattern = f"(^ {{{shift_left}}})"
        document = re.sub(pattern, "", document, flags=re.MULTILINE)
    document = re.sub(r"^ +$", "", document, flags=re.MULTILINE)
    return document.strip("\n")
