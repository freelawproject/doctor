import re

import pdfplumber
from pdfplumber.ctm import CTM
import pytesseract
from pytesseract import Output
import pandas as pd
from PIL import Image


def is_skewed(obj: dict) -> bool:
    """Check if a PDF plumber dict is skewed

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

    Strip margin refers only to top and bottom margin here

    :param page: PdfPlumber page
    :param strip_margin: a flag to crop out the margin of a document and skewed content
    :return: Text from the pdf plumber page
    """
    if strip_margin:
        # Crop margins and remove skewed text
        _, _, width, height = page.bbox
        pixels_per_inch = width / 8.5
        bbox = (
            0,
            pixels_per_inch * 1,  # 1 inch down from top
            width,  #
            pixels_per_inch * 10,  # 10 inches from top (1 inch from bottom)
        )
        try:
            page_text = (
                page.crop(bbox)
                .filter(is_skewed)
                .extract_text(
                    layout=True, keep_blank_chars=True, y_tolerance=5, y_density=25
                )
            )
        except ValueError:
            # If bounding box is non standard we do not want to apply strip margin
            page_text = page.extract_text(
                layout=True, keep_blank_chars=True, y_tolerance=5, y_density=25
            )

    else:
        page_text = page.extract_text(
            layout=True, keep_blank_chars=True, y_tolerance=5, y_density=25
        )
    page_text = remove_excess_whitespace(page_text)
    return page_text


def has_images(page: pdfplumber.pdf.Page) -> bool:
    """Does the page have images that are large enough to contain text

    :param page: pdf plumber page
    :return: True if page contains images of a certain size
    """
    return any(
        [
            image
            for image in page.images
            if image["width"] > 10 and image["height"] > 10
        ]
    )


def has_text_annotations(page: pdfplumber.pdf.Page) -> bool:
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
    for separator in [r")", "§", ":"]:
        pattern = rf"(.* +{re.escape(separator)} .*\n)"
        matches = list(re.finditer(pattern, page_text))
        central_matches = [
            match.group().rindex(separator)
            for match in matches
            if 30 <= match.group().rindex(separator) <= 70
        ]
        if len(central_matches) < 3:
            continue  # Skip this separator if less than 3 matches found
        # Determine the longest position of the separator
        longest = max(central_matches)
        page = []
        for row in page_text.splitlines():
            index = row.find(f" {separator}")
            addition = (longest - index) * " "
            row = row.replace(f" {separator}", f"{addition}{separator}")
            page.append(row)
        return "\n".join(page)
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
        or has_text_annotations(page)
        or has_images(page)
        or len(page.curves) > 10
    ):
        return True
    return False


def convert_pdf_page_to_image(
    page: pdfplumber.pdf.Page, strip_margin: bool
) -> Image:
    """Convert page to image and crop margin if applicable

    :param page: the pdf page
    :param strip_margin: whether to crop the margin
    :return: The cropped page image
    """
    img = page.to_image(resolution=300)
    _, _, w, h = page.bbox
    width = w * img.scale

    if strip_margin == True:
        pixels_per_inch = width / 8.5
        bbox = (
            pixels_per_inch * 0.5,  # .5"  from left edge
            pixels_per_inch * 0.5,  # .5" down from top
            pixels_per_inch * 8,  # 8" from left edge (.5" from right)
            pixels_per_inch * 10.5,  # 10.5" from top (.5" from bottom)
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

    #  Detailed Parameters for `pytesseract.image_to_data`:
    #  - config: str
    #      Additional Tesseract configuration options.
    #      - `-c preserve_interword_spaces=1`: Preserve spaces between words as they appear in the image.
    #      - `-c tessedit_do_invert=0`: Do not invert the image colors.
    #      - `--psm 6`: Page segmentation mode 6, which assumes a single uniform block of text.
    #      - `-l eng`: Use the English language for OCR.
    #  - output_type: pytesseract.Output.DICT
    #      Specifies that the output should be a dictionary of OCR data.
    #
    #  Reference:
    #  Tesseract OCR documentation: https://github.com/tesseract-ocr/tesseract/blob/master/doc/tesseract.1.asc

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

    This function determines if a word should be added to the page content
    and adds the word.

    :param word_dict: the word object from tesseract
    :param width: The width of the document
    :param strip_margin: should we strip the margin
    :return: The text with space
    """
    pixels_per_inch = width / 8.5
    if strip_margin:
        left_margin = 1 * pixels_per_inch  #
        right_margin = 7.5 * pixels_per_inch
    else:
        left_margin = 0.5 * pixels_per_inch
        right_margin = 8.0 * pixels_per_inch

    # tesseract provides confidence values for its OCR outputs. We use those
    # confidence values to determine if something is a good OCR output, a
    # likely artifact and should be excluded or is bad ocr but not an artifact.

    word = word_dict["text"]
    conf = word_dict["conf"]

    no_confidence = 0
    very_low_confidence = 5
    low_confidence = 40
    short_word_len = 3
    long_word_len = 20
    if (
        word_dict["left"] + word_dict["width"] < left_margin
        and conf < low_confidence
    ):
        # If a word has confidence below 40, a number that usually equates to 3 to 5
        # standard deviations from confidences found in other words is entirely in the
        # margin of the page - its likely an artifact as well.
        word = " " * len(word)
    elif (conf == no_confidence and len(word) <= short_word_len) or word_dict[
        "left"
    ] == 0:
        # If a word has a zero confidence or starts on the left most edge of the paper
        # we return it as an empty string. It is likely an artifact.
        word = " " * len(word)
    elif conf < very_low_confidence and (
        len(word) <= short_word_len or len(word) > long_word_len
    ):
        # If a confidence is below 5 - for a very short word - or for a very long word
        # its likely part of the document but we have no idea so we return a square
        # box to indicate that. This is often caused by stamps or lines in case captions
        word = "□" * len(word)
    elif conf < low_confidence and word_dict["left"] > right_margin:
        # Finally if a low confidence word starts in the right margin - its likely a
        # bad OCR that is multiple standard deviations away so we return the word as
        # empty squares.
        word = "□" * len(word)

    return f"{word} "


def cleanup_content(content: str, page_number: int) -> str:
    """Reduce legal document line clutter

    This function performs several operations to clean up the text extracted from legal documents:

    1. On the first page, it smooths out vertical lines if they are detected.
    2. It removes pipes ('|') that might start a line repeatedly.
    3. It removes artifacts that appear at the end of a line of text, specifically single characters
       following at least 10 whitespace characters, reducing right margin edge artifacts.
    4. It removes excess left margin whitespace to improve readability and formatting.

    Example:
    If the pipes below represent the page edge (not characters):
    |       we can remove the
    |    the left whitespace
    |    and shift this entire
    |    page over four characters
    |    which keeps formatting and
    |    makes the text easier to
    |    read and process with the API.

    :param content: the page content extracted
    :param page_number: the page number
    :return: the cleaned up text
    """
    # remove floating pipes
    pattern = r"\s{4,}\| $"
    # Substitute the matched pipe with an empty string
    content = re.sub(pattern, "", content, flags=re.MULTILINE)

    # remove floating artifacts from the right side
    pattern = r"\s{10,}[a-zA-Z0-9|] $"
    content = re.sub(pattern, "", content, flags=re.MULTILINE)

    # shift text left if possible and remove excess start and end whitespace
    content = remove_excess_whitespace(content)
    if page_number == 1:
        content = adjust_caption_lines(content)

    return f"{content}\n"


def remove_excess_whitespace(document: str) -> str:
    """Remove excess whitespace from OCR

    This function removes empty lines of text at the start and end of a document
    and shifts the page left if possible

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
