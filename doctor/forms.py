import hashlib
import json
import tempfile
import uuid

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator


class BaseAudioFile(forms.Form):
    file = forms.FileField(label="document", required=True)


class BaseFileForm(forms.Form):
    """"""

    file = forms.FileField(label="document", required=True)

    def temp_save_file(self, fp):
        with open(fp, "wb") as f:
            for chunk in self.cleaned_data["file"].chunks():
                f.write(chunk)

    def clean_file(self):
        file = self.cleaned_data.get("file", False)
        if not file:
            raise ValidationError("File is missing.")
        self.cleaned_data["extension"] = file.name.split(".")[-1]
        self.cleaned_data["original_filename"] = file.name
        self.prep_file()
        return file

    def prep_file(self):
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=f".{self.cleaned_data['extension']}"
        ) as fp:
            self.cleaned_data["fp"] = fp.name
            self.temp_save_file(fp.name)


class AudioForm(BaseAudioFile):
    """"""

    audio_data = forms.JSONField(label="audio-data", required=False)

    def clean(self):
        self.cleaned_data["fp"] = f"/tmp/audio_{uuid.uuid4().hex}"
        if self.cleaned_data.get("file", None):
            filename = self.cleaned_data["file"].name
            self.cleaned_data["extension"] = filename.split(".")[-1]
        return self.cleaned_data


class ImagePdfForm(forms.Form):
    sorted_urls = forms.CharField(required=True, label="sorted-urls")

    def clean(self):
        self.cleaned_data["sorted_urls"] = json.loads(
            self.cleaned_data["sorted_urls"]
        )
        return self.cleaned_data


class MimeForm(forms.Form):
    file = forms.FileField(label="document", required=False)
    mime = forms.BooleanField(label="mime", required=False)

    def temp_save_file(self, fp):
        with open(fp, "wb") as f:
            for chunk in self.cleaned_data["file"].chunks():
                f.write(chunk)

    def clean_file(self):
        """
        Performs field-level cleaning and validation for the 'file' field

        NOTE ON VALIDATION ORDER:
        Django's internal form validation process automatically calls methods
        named `clean_<fieldname>()` (like this one) first. If successful, the
        cleaned value is added to the shared storage, `self.cleaned_data`.

        Django then calls the general `clean()` method last, which relies on
        `self.cleaned_data` being fully populated. This means `clean_file()`
        must NOT be called manually from within `clean()`, as it will execute
        twice and overwrite or lose data (causing side effects).
        """
        file = self.cleaned_data.get("file")
        if not file:
            raise ValidationError("File is missing.")

        self.cleaned_data["original_filename"] = file.name
        self.cleaned_data.setdefault("filename", "unknown")

        # Create a tempfile without extension so exiftool/magika detection isn't biased by extension
        with tempfile.NamedTemporaryFile(delete=False, suffix="") as fp:
            self.cleaned_data["fp"] = fp.name
            self.temp_save_file(fp.name)

        return file


class ThumbnailForm(forms.Form):
    file = forms.FileField(
        label="document",
        required=True,
        validators=[FileExtensionValidator(["pdf"])],
    )
    max_dimension = forms.IntegerField(label="max-dimension", required=False)
    pages = forms.Field(label="pages", required=False)

    def clean(self):
        """"""
        if self.cleaned_data.get("pages"):
            self.cleaned_data["pages"] = json.loads(self.cleaned_data["pages"])

        if not self.cleaned_data["max_dimension"]:
            self.cleaned_data["max_dimension"] = 350
        return self.cleaned_data


class DocumentForm(BaseFileForm):
    ocr_available = forms.BooleanField(label="ocr-available", required=False)
    mime = forms.BooleanField(label="mime", required=False)
    strip_margin = forms.BooleanField(label="strip-margin", required=False)


class StructuredOpinionForm(forms.Form):
    """Parameters for the structured opinion extraction endpoint.

    A digital (text-based) court PDF plus the court it came from.
    centralia reads only the courts it has been ported to, so the
    court id is required rather than sniffed.
    """

    file = forms.FileField(
        label="document",
        required=True,
        validators=[FileExtensionValidator(["pdf"])],
    )
    court_id = forms.CharField(label="court-id", required=True)
    allow_pending = forms.BooleanField(label="allow-pending", required=False)

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if not file:
            raise ValidationError("File is missing.")
        self.cleaned_data["original_filename"] = file.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as fp:
            self.cleaned_data["fp"] = fp.name
            with open(fp.name, "wb") as f:
                for chunk in file.chunks():
                    f.write(chunk)
        return file


class BitonalPdfForm(forms.Form):
    """Parameters for the bitonal conversion endpoint.

    The input arrives either as a multipart upload (``file``) or as a
    presigned GET URL (``input_url``) — exactly one of the two. When
    ``output_url`` is present the result is uploaded there; otherwise
    it is returned inline in the response.
    """

    file = forms.FileField(
        label="document",
        required=False,
        validators=[FileExtensionValidator(["pdf"])],
    )
    input_url = forms.CharField(label="input-url", required=False)
    output_url = forms.CharField(label="output-url", required=False)
    dpi = forms.IntegerField(
        label="dpi", required=False, min_value=72, max_value=600
    )
    threshold = forms.IntegerField(
        label="threshold", required=False, min_value=0, max_value=255
    )
    first_page = forms.IntegerField(
        label="first-page", required=False, min_value=1
    )
    last_page = forms.IntegerField(
        label="last-page", required=False, min_value=1
    )
    # No max_value: a field would bind the ceiling at import time,
    # so a test could not override the setting. clean() reads it.
    page_timeout = forms.IntegerField(
        label="page-timeout", required=False, min_value=1
    )
    total_timeout = forms.IntegerField(
        label="total-timeout", required=False, min_value=1
    )

    def clean(self):
        # Structural validation only. The egress allowlist check
        # happens in the view, where a rejected URL can surface as
        # its documented EGRESS_BLOCKED error code instead of being
        # flattened into VALIDATION_FAILED.
        file = self.cleaned_data.get("file")
        input_url = self.cleaned_data.get("input_url")
        if file and input_url:
            raise ValidationError(
                "Send either 'file' or 'input_url', not both."
            )
        if not file and not input_url:
            raise ValidationError("Send one of 'file' or 'input_url'.")

        if not self.cleaned_data.get("dpi"):
            self.cleaned_data["dpi"] = 300
        if self.cleaned_data.get("threshold") is None:
            self.cleaned_data["threshold"] = 128

        # The settings are the default and the ceiling both: the
        # caller tunes a slow volume without a doctor release, and
        # doctor keeps the outer bound on how long a worker is held.
        # An over-ceiling value is rejected rather than clamped, so
        # the caller learns the limit instead of guessing at it.
        ceilings = (
            (
                "page_timeout",
                settings.DOCTOR_BITONAL_PAGE_TIMEOUT_MAX_SECONDS,
            ),
            ("total_timeout", settings.DOCTOR_BITONAL_TIMEOUT_SECONDS),
        )
        for field, ceiling in ceilings:
            value = self.cleaned_data.get(field)
            if value is not None and value > ceiling:
                self.add_error(
                    field,
                    f"Must be {ceiling} seconds or less.",
                )

        if not file or self.errors:
            # Copying and hashing the upload is the expensive part of
            # validation, so skip it once the request is rejected: a
            # 500MB body must not pay for a bad dpi. The view reads fp
            # and source_sha256 only on a valid form, and cleanup_form
            # tolerates a missing fp.
            return self.cleaned_data

        # Hash while writing, like stream_url_to_file and
        # put_file_to_url do, so the view never re-reads the upload
        # just to compute source_sha256.
        digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as fp:
            self.cleaned_data["fp"] = fp.name
            with open(fp.name, "wb") as f:
                for chunk in file.chunks():
                    f.write(chunk)
                    digest.update(chunk)
        self.cleaned_data["source_sha256"] = digest.hexdigest()
        return self.cleaned_data
