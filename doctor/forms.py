import json
import tempfile
import uuid

from django import forms


class AudioForm(forms.Form):

    file = forms.FileField(label="document", required=True)
    audio_data = forms.JSONField(label="audio-data", required=False)

    def clean(self):
        self.cleaned_data["fp"] = f"/tmp/audio_{uuid.uuid4().hex}.mp3"
        self.cleaned_data["extension"] = self.cleaned_data["file"].name.split(".")[-1]
        return self.cleaned_data


class ImagePdfForm(forms.Form):

    sorted_urls = forms.CharField(required=True, label="sorted-urls")

    def clean(self):
        self.cleaned_data["sorted_urls"] = json.loads(self.cleaned_data["sorted_urls"])
        return self.cleaned_data


class MimeForm(forms.Form):
    file = forms.FileField(label="document", required=False)
    mime = forms.BooleanField(label="mime", required=False)

    def clean(self):
        self.cleaned_data["filename"] = "unknown"


class DocumentForm(forms.Form):

    file = forms.FileField(label="document", required=False)
    ocr_available = forms.BooleanField(label="ocr-available", required=False)
    mime = forms.BooleanField(label="mime", required=False)
    max_dimension = forms.IntegerField(label="max-dimension", required=False)
    pages = forms.Field(label="pages", required=False)

    def temp_save_file(self, fp):
        with open(fp, "wb") as f:
            for chunk in self.cleaned_data["file"].chunks():
                f.write(chunk)

    def clean(self):
        """"""
        self.cleaned_data["filename"] = self.cleaned_data["file"].name
        self.cleaned_data["extension"] = self.cleaned_data["file"].name.split(".")[-1]
        if not self.cleaned_data["max_dimension"]:
            self.cleaned_data["max_dimension"] = 350
        fp = tempfile.NamedTemporaryFile(
            delete=False, suffix=f'.{self.cleaned_data["extension"]}'
        )
        self.cleaned_data["tmp_dir"] = tempfile.TemporaryDirectory()
        if self.cleaned_data.get("pages"):
            self.cleaned_data["pages"] = json.loads(self.cleaned_data["pages"])
        self.cleaned_data["fp"] = fp.name
        self.temp_save_file(fp.name)
        return self.cleaned_data
