"""Bitonal (1-bit CCITT G4) PDF conversion.

Converts scanned PDFs to bitonal, one page at a time, keeping memory
flat regardless of document size:

1. Rasterize a single page to grayscale with poppler's ``pdftoppm
   -gray``. ``-mono`` is deliberately not used because it dithers.
2. Threshold with numpy and pack to 1-bit rows with ``np.packbits``.
3. Encode CCITT Group 4 through Pillow's TIFF writer, as a single
   strip per page.
4. Embed the raw G4 stream as a ``CCITTFaxDecode`` image XObject with
   pikepdf. The stream is written as-is: no decode, no re-encode.

Each output page copies its MediaBox from the source page, never
inferring geometry from image dimensions and DPI, so documents with
mixed page sizes keep their layout and detection boxes expressed
relative to the page rect stay valid.
"""

import io
import subprocess
import threading
import time

import numpy as np
import pikepdf
from django.conf import settings
from PIL import Image, TiffImagePlugin
from pypdf import PdfReader
from pypdf.errors import PdfReadError

# TIFF tag ids (PIL.TiffTags exposes no named constants for these)
TIFF_STRIP_OFFSETS = 273
TIFF_STRIP_BYTE_COUNTS = 279

# Pillow sizes TIFF strips from TiffImagePlugin.STRIP_SIZE (~64KB by
# default, which chunks a page into several G4 strips). G4 strips
# restart the coding context, so a multi-strip payload cannot be
# embedded as one CCITTFaxDecode stream: raise the limit around the
# save so every page is one strip. The attribute is module-global,
# hence the lock (sync views may run concurrently on the threadpool).
_STRIP_SIZE_ONE_PAGE = 2**28
_strip_size_lock = threading.Lock()


class BitonalError(Exception):
    """A conversion or transport failure with a machine-usable code.

    :param error_code: One of the documented error codes for the
        bitonal endpoint (e.g. INVALID_PDF, RESULT_URL_EXPIRED).
    :param message: Human-readable detail.
    :param status: HTTP status the view should respond with.
    """

    def __init__(self, error_code: str, message: str, status: int = 500):
        self.error_code = error_code
        self.message = message
        self.status = status
        super().__init__(f"{error_code}: {message}")


def rasterize_page_to_gray(
    input_path: str,
    page_number: int,
    dpi: int,
    timeout: float | None = None,
) -> Image.Image:
    """Rasterize a single PDF page to a grayscale PIL image.

    Uses one ``pdftoppm`` call per page so peak memory stays at one
    decoded page no matter how large the document is.

    :param input_path: Path of the source PDF.
    :param page_number: 1-indexed page number.
    :param dpi: Rasterization resolution.
    :param timeout: Seconds pdftoppm may take; defaults to the
        DOCTOR_BITONAL_PAGE_TIMEOUT_SECONDS setting. Without it, a
        malformed page can make poppler spin forever.
    :return: Grayscale (mode "L") image of the page.
    """
    if timeout is None:
        timeout = settings.DOCTOR_BITONAL_PAGE_TIMEOUT_SECONDS
    command = [
        "pdftoppm",
        "-singlefile",
        "-gray",
        "-r",
        str(dpi),
        "-f",
        str(page_number),
        input_path,
    ]
    try:
        p = subprocess.run(command, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise BitonalError(
            "CONVERSION_FAILED",
            f"pdftoppm timed out after {timeout:.0f}s on page {page_number}",
        ) from e
    if p.returncode != 0 or not p.stdout:
        raise BitonalError(
            "CONVERSION_FAILED",
            f"pdftoppm failed on page {page_number}: "
            f"{p.stderr.decode(errors='replace')[:500]}",
        )
    return Image.open(io.BytesIO(p.stdout)).convert("L")


def gray_to_g4(gray: Image.Image, threshold: int) -> bytes:
    """Threshold a grayscale image and encode it as a raw G4 stream.

    Thresholding goes through ``np.packbits`` rather than PIL's
    ``convert("1")``, which is faster and, more importantly, avoids
    PIL's default Floyd-Steinberg dithering: dithered speckle is the
    artifact this endpoint exists to avoid and it bloats G4 badly.

    :param gray: Grayscale (mode "L") page image.
    :param threshold: 0-255; pixels above it become white.
    :return: The raw single-strip CCITT G4 stream.
    """
    arr = np.asarray(gray)
    packed = np.packbits(arr > threshold, axis=1)
    bitonal = Image.frombytes("1", gray.size, packed.tobytes())

    buffer = io.BytesIO()
    with _strip_size_lock:
        default_strip_size = TiffImagePlugin.STRIP_SIZE
        TiffImagePlugin.STRIP_SIZE = _STRIP_SIZE_ONE_PAGE
        try:
            bitonal.save(buffer, format="TIFF", compression="group4")
        finally:
            TiffImagePlugin.STRIP_SIZE = default_strip_size

    buffer.seek(0)
    tiff = Image.open(buffer)
    offsets = tiff.tag_v2[TIFF_STRIP_OFFSETS]
    counts = tiff.tag_v2[TIFF_STRIP_BYTE_COUNTS]
    if len(offsets) != 1:
        raise BitonalError(
            "CONVERSION_FAILED",
            f"expected a single G4 strip, got {len(offsets)}",
        )
    data = buffer.getvalue()
    return data[offsets[0] : offsets[0] + counts[0]]


def _placement_matrix(
    rotation: int, box: tuple[float, float, float, float]
) -> str:
    """Build the ``cm`` matrix that fills the page box with the raster.

    ``pdftoppm`` renders the page as displayed, i.e. with /Rotate
    applied. Copying /Rotate to the output page means the viewer will
    rotate again, so the raster is placed pre-rotated by the inverse.

    :param rotation: Source page /Rotate, normalized to 0/90/180/270.
    :param box: Source MediaBox as (x0, y0, x1, y1).
    :return: The six ``cm`` operands as a string.
    """
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    matrices = {
        0: (w, 0, 0, h, x0, y0),
        90: (0, h, -w, 0, x1, y0),
        180: (-w, 0, 0, -h, x1, y1),
        270: (0, -h, w, 0, x0, y1),
    }
    return " ".join(f"{v:.4f}" for v in matrices[rotation])


def add_bitonal_page(
    pdf: pikepdf.Pdf,
    g4: bytes,
    size: tuple[int, int],
    box: tuple[float, float, float, float],
    rotation: int,
) -> None:
    """Append a page wrapping a raw G4 stream to an output PDF.

    :param pdf: The output document being assembled.
    :param g4: Raw single-strip CCITT G4 data.
    :param size: Raster (width, height) in pixels.
    :param box: Source MediaBox as (x0, y0, x1, y1).
    :param rotation: Source page /Rotate, normalized to 0/90/180/270.
    """
    width, height = size
    image = pikepdf.Stream(pdf, b"")
    # write() stores the data as already-encoded, so the G4 stream
    # goes into the file untouched. BlackIs1 must be True because
    # Pillow writes G4 with photometric=1 (min-is-black).
    image.write(
        g4,
        filter=pikepdf.Name("/CCITTFaxDecode"),
        decode_parms=pikepdf.Dictionary(
            K=-1, Columns=width, Rows=height, BlackIs1=True
        ),
    )
    image.Type = pikepdf.Name("/XObject")
    image.Subtype = pikepdf.Name("/Image")
    image.Width = width
    image.Height = height
    image.BitsPerComponent = 1
    image.ColorSpace = pikepdf.Name("/DeviceGray")

    content = f"q {_placement_matrix(rotation, box)} cm /Im0 Do Q".encode()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=list(box),
        Resources=pikepdf.Dictionary(
            XObject=pikepdf.Dictionary(Im0=pdf.make_indirect(image))
        ),
        Contents=pdf.make_indirect(pikepdf.Stream(pdf, content)),
    )
    if rotation:
        page.Rotate = rotation
    pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))


def convert_pdf_to_bitonal(
    input_path: str,
    output_path: str,
    dpi: int,
    threshold: int,
    first_page: int | None = None,
    last_page: int | None = None,
) -> dict:
    """Convert a PDF (or a 1-indexed inclusive page range) to bitonal.

    :param input_path: Path of the source PDF.
    :param output_path: Path the bitonal PDF is written to.
    :param dpi: Rasterization resolution.
    :param threshold: 0-255; pixels above it become white.
    :param first_page: First page to convert; defaults to 1.
    :param last_page: Last page to convert; defaults to the last.
    :return: Conversion metadata (page counts and parameters).
    """
    try:
        # Extract only mediabox/rotation so the handle closes here,
        # not at GC.
        with open(input_path, "rb") as f:
            reader = PdfReader(f)
            source_pages = [
                (
                    tuple(float(v) for v in page.mediabox),
                    (page.rotation or 0) % 360,
                )
                for page in reader.pages
            ]
    except (
        # The same tuple get_page_count uses: pypdf raises TypeError,
        # KeyError and AssertionError (not just PdfReadError) on
        # corrupt xref and object-stream structures.
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AssertionError,
        PdfReadError,
    ) as e:
        raise BitonalError(
            "INVALID_PDF", f"could not read source PDF: {e}", status=400
        ) from e
    page_count = len(source_pages)
    if page_count == 0:
        raise BitonalError("INVALID_PDF", "source PDF has no pages", 400)

    first_page = first_page or 1
    last_page = last_page or page_count
    if not 1 <= first_page <= last_page <= page_count:
        raise BitonalError(
            "PAGE_RANGE_INVALID",
            f"range {first_page}-{last_page} invalid for a "
            f"{page_count}-page document",
            status=400,
        )

    # Without a whole-conversion budget, the per-page timeout still
    # allows pages x page-timeout worst case.
    total_timeout = settings.DOCTOR_BITONAL_TIMEOUT_SECONDS
    page_timeout = settings.DOCTOR_BITONAL_PAGE_TIMEOUT_SECONDS
    deadline = time.monotonic() + total_timeout

    pdf = pikepdf.new()
    for number in range(first_page, last_page + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BitonalError(
                "CONVERSION_FAILED",
                f"conversion exceeded the {total_timeout}s budget "
                f"at page {number}",
            )
        box, rotation = source_pages[number - 1]
        if rotation not in (0, 90, 180, 270):
            raise BitonalError(
                "CONVERSION_FAILED",
                f"page {number} has unsupported rotation {rotation}",
            )
        gray = rasterize_page_to_gray(
            input_path, number, dpi, timeout=min(page_timeout, remaining)
        )
        g4 = gray_to_g4(gray, threshold)
        add_bitonal_page(pdf, g4, gray.size, box, rotation)
    pdf.save(output_path)

    # Bitonal is the one 1:1 page-preserving consumer: the shard merge
    # relies on no page ever being dropped, added or resized, so
    # re-read what was actually written and refuse to ship anything
    # that violates that.
    expected = last_page - first_page + 1
    with open(output_path, "rb") as f:
        result = PdfReader(f)
        written_boxes = [
            tuple(float(v) for v in page.mediabox) for page in result.pages
        ]
    if len(written_boxes) != expected:
        raise BitonalError(
            "PAGE_COUNT_MISMATCH",
            f"wrote {len(written_boxes)} pages, expected {expected}",
        )
    for offset, written_box in enumerate(written_boxes):
        source_box = source_pages[first_page - 1 + offset][0]
        if any(abs(a - b) > 0.01 for a, b in zip(source_box, written_box)):
            raise BitonalError(
                "PAGE_GEOMETRY_MISMATCH",
                f"page {first_page + offset} MediaBox {written_box} "
                f"does not match source {source_box}",
            )

    return {
        "pages": expected,
        "page_count": page_count,
        "dpi": dpi,
        "threshold": threshold,
        "first_page": first_page,
        "last_page": last_page,
    }
