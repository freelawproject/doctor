import re

import pdfplumber
from pdfplumber.ctm import CTM
import pytesseract
from pytesseract import Output
import pandas as pd
from PIL import Image


def deskew(obj) -> bool:
    """Remove skewed text from a page

    Traditionally this is only seen in circular stamps which confuses the
    content, or in perpendicular text of the ninth circuit courts which also
    confuses the text.
    """
    if (matrix := obj.get("matrix")) is None:
        return True

    # Remove Skew
    my_char_ctm = CTM(*matrix)
    if my_char_ctm.skew_x != 0:
        return False
    return True


def get_page_text(page: pdfplumber.PDF.pages, strip_margin: bool):
    """Extract page text

    Using pdf plumber extract out the text of the document that is not
    skewed (ie a stamp of approval) and extract out text removing blue text

    :param page: pdf plumber page
    :param strip_margin: a flag to crop out the margin of a document and skewed content
    :return: text
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


def page_images(page):
    """Does the page have images of a certain size

    Meant to exclude images that might be lines
    """
    for img in page.images:
        if (
            img.get("width") / page.width * img.get("height") / page.height
            > 0.1
        ) or img.get("width") * img.get("width") > 10:
            return True
    return False


def page_annotations(page):
    """Does the page have annotations which could contain text

    :param page: pdf plumber
    """
    if page.annots:
        anno_types = [
            str(annot.get("data").get("Subtype")) for annot in page.annots
        ]
        if "/'FreeText'" in anno_types or "/'Widget'" in anno_types:
            return True
    return False


def find_average_char_width(block_data):
    """Average character width for a block of text

    :param block_data:
    :return: average character width
    """
    fd = block_data[block_data.text.str.len() > 0]
    return (fd.width / fd.text.str.len()).mean()


# def validate_ocr_text(row, img):
#     """Review OCR results for low confidence and reprocess if necessary
#
#     :param row:
#     :param img:
#     :return:
#     """
#     # If low confidence in the margins of drop character as likely artifact
#     if row["left"] < 370 and row["conf"] <= 40:
#         row["text"] = " " * len(row["text"])
#     # if very low confidence and small - reprocess word with OCR for single line
#     # this will give us a better chance to get the word right or remove junk
#     elif row["conf"] < 10 and len(row["text"]) >= 3:
#         # Give us a buffer around the word to increase OCR-ability
#         bbox = (
#             row["left"] - 5,
#             row["top"] - 3,
#             row["left"] + row["width"] + 5,
#             row["top"] + row["height"] + 3,
#         )
#         config = "f'-c preserve_interword_spaces=1x1 --psm 7 -l eng'"
#         word_df = pd.DataFrame(
#             pytesseract.image_to_data(
#                 img.crop(bbox), config=config, output_type=Output.DICT
#             )
#         )
#         # If new word above low confidence - use new word
#         new_words = " ".join(
#             word_df.loc[word_df["conf"] > 10, "text"].tolist()
#         )
#         if new_words:
#             row["text"] = new_words
#         else:
#             # Otherwise identify unknown word/words with empty box
#             row["text"] = "□" * len(row["text"])
#     return row


def validate_ocr_text(row, img):
    """

    :param row:
    :param img:
    :return:
    """
    if row["left"] < 370 and row["conf"] <= 40:
        row["text"] = " " * len(row["text"])
    elif row["conf"] < 10 and len(row["text"]) >= 3:
        bbox = (
            row["left"] - 5,
            row["top"] - 3,
            row["left"] + row["width"] + 5,
            row["top"] + row["height"] + 3,
        )
        word_df = pd.DataFrame(
            pytesseract.image_to_data(
                img.crop(bbox),
                config="-c preserve_interword_spaces=1x1 --psm 7 -l eng",
                output_type=Output.DICT,
            )
        )
        new_words = " ".join(
            word_df.loc[word_df["conf"] > 10, "text"].tolist()
        )
        if new_words:
            row["text"] = new_words
        else:
            row["text"] = "□" * len(row["text"])
    return row["text"] + " "


def add_newlines(row: pd.Series, state: dict) -> dict:
    """Add new linebreaks into the ocr'd page

    identify where line breaks should be added

    :param row: the row of data from tesseract
    :param state: the location data used to decide where line breaks should be
    :return:
    """
    prev = state["prev_row"]
    max_y = state["max_y"]
    new_line = prev["line_num"] != row["line_num"] if max_y > 0 else True
    new_paragraph = prev["par_num"] != row["par_num"] if max_y > 0 else True

    if new_line:
        state["page_text"] += "\n"
        state["indent"] = 0
    if new_paragraph:
        # Add a second line break for new paragraphs for good measure
        state["page_text"] += "\n"
        state["indent"] = 0

    if new_line and not new_paragraph and state["max_y"] > 0:
        diff = row["top"] - state["max_y"]
        if 200 > diff > 130:
            state["page_text"] += "\n"
        elif diff > 200:
            state["page_text"] += "\n\n"
        state["max_y"] = 0

    state["max_y"] = max(state["max_y"], row["top"] + row["height"])
    return state


def insert_indentation(row: pd.Series, state: dict) -> dict:
    """Insert indentation in each row of text

    :param row: panda row
    :param state: dictionary of position text data
    :return: dictionary of position text data
    """
    indent = int((row["left"]) / state["char_width"]) - state["indent"]
    prev = state["prev_row"]
    if prev is not None:
        spacing = row.get("left") - (prev.get("left") + prev.get("width"))
    else:
        spacing = 0
    if (spacing > 25 or state["indent"] == 0) and indent >= 8:
        state["page_text"] += " " * indent
    state["indent"] += len(row["text"]) + indent + 1
    state["prev_row"] = row
    return state


def format_text_by_block(block: pd.DataFrame, img: Image) -> str:
    """Process blocks of text

    Insert whitespace and validate the OCR results

    This includes removing certain low confidence characters, adding line breaks
    adding indentations and inserting empty boxes over other OCR results

    :param block: The block of text
    :param img: The page image
    :return: Page text
    """
    state = {
        "page_text": "",
        "char_width": find_average_char_width(block),
        "prev_row": None,
        "indent": 0,
        "max_y": 0,
    }

    for index, row in block.iterrows():
        state = add_newlines(row, state)
        state = insert_indentation(row, state)
        state["page_text"] += validate_ocr_text(row, img)
        # state['prev_row'] = row

    page_text = re.sub(r"^ +$", "", state["page_text"], flags=re.MULTILINE)
    return page_text.strip("\n")


def extract_block_content(tesseract_dict: dict) -> list:
    """Order tesseract content

    :param tesseract_dict:
    :return: sorted list of block content
    """
    df = pd.DataFrame(tesseract_dict)
    fd = df[(df.conf != -1)]
    sorted_blocks = (
        fd.groupby("block_num").first().sort_values("top").index.tolist()
    )
    return [fd[fd["block_num"] == block] for block in sorted_blocks]


def process_page_with_ocr(page: pdfplumber.PDF.pages) -> str:
    """OCR a page of text and format it

    :param page: pdf plumber page
    :return: page text
    """
    image = page.to_image(resolution=300).original

    custom_config = f"-c preserve_interword_spaces=1x1 -c tessedit_do_invert=0 --psm 6 -l eng"
    tesseract_dict = pytesseract.image_to_data(
        image, config=custom_config, output_type=Output.DICT
    )
    ordered_page_blocks = extract_block_content(tesseract_dict)

    page_text = ""
    for block in ordered_page_blocks:
        page_text += format_text_by_block(block, image)
    page_text = re.sub(r"^\s+\n|$", "", page_text, 1, flags=re.MULTILINE)
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
    document = re.sub(r"^ +$", "", document, flags=re.MULTILINE).strip("\n")

    return document
