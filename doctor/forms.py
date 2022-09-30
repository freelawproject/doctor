import json
import tempfile
import uuid

from django import forms
from django.core.exceptions import ValidationError


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
        self.prep_file()
        return file

    def prep_file(self):
        fp = tempfile.NamedTemporaryFile(
            delete=False, suffix=f'.{self.cleaned_data["extension"]}'
        )
        self.cleaned_data["tmp_dir"] = tempfile.TemporaryDirectory()
        self.cleaned_data["fp"] = fp.name
        self.temp_save_file(fp.name)


class AudioForm(BaseAudioFile):
    """"""

    audio_data = forms.JSONField(label="audio-data", required=False)

    def clean(self):
        self.cleaned_data["fp"] = f"/tmp/audio_{uuid.uuid4().hex}.mp3"
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

    def clean(self):
        file = self.cleaned_data.get("file", False)
        if not file:
            raise ValidationError("File is missing.")

        self.cleaned_data["filename"] = "unknown"


class ThumbnailForm(forms.Form):
    file = forms.FileField(label="document", required=True)
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

    def clean(self):
        self.clean_file()
        return self.cleaned_data
