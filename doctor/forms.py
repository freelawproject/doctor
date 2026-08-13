import json
import tempfile
import uuid

from django import forms
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

    def clean(self):
        # Imported here to keep module import light; tasks pulls in
        # the whole extraction stack.
        from doctor.lib.bitonal import BitonalError
        from doctor.tasks import validate_egress_url

        file = self.cleaned_data.get("file")
        input_url = self.cleaned_data.get("input_url")
        if file and input_url:
            raise ValidationError(
                "Send either 'file' or 'input_url', not both."
            )
        if not file and not input_url:
            raise ValidationError("Send one of 'file' or 'input_url'.")
        for url in (input_url, self.cleaned_data.get("output_url")):
            if url:
                try:
                    validate_egress_url(url)
                except BitonalError as e:
                    raise ValidationError(e.message) from e

        if not self.cleaned_data.get("dpi"):
            self.cleaned_data["dpi"] = 300
        if self.cleaned_data.get("threshold") is None:
            self.cleaned_data["threshold"] = 128

        if file:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".pdf"
            ) as fp:
                self.cleaned_data["fp"] = fp.name
                with open(fp.name, "wb") as f:
                    for chunk in file.chunks():
                        f.write(chunk)
        return self.cleaned_data
