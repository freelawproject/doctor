# Note: Force M1 to emulate amd64
FROM --platform=linux/amd64 python:3.10-slim

RUN apt-get update --option "Acquire::Retries=3" --quiet=2 && \
    apt-get install -y --no-install-recommends apt-utils && \
    apt-get install -y python3-pip poppler-utils curl \
    libleptonica-dev tesseract-ocr libtesseract-dev \
    g++ libz-dev libjpeg-dev build-essential qpdf && \
    apt-get install \
        --option "Acquire::Retries=3" \
        --no-install-recommends \
        --assume-yes \
        --quiet=2 \
        `# Document extraction and OCR tools` \
        antiword docx2txt ghostscript libwpd-tools \
        `# Audio extraction/manipulation tools` \
         ffmpeg libmagic1 \
        `# Image & OCR tools` \
        imagemagick \
        `# Other dependencies` \
        libffi-dev libxml2-dev libxslt-dev python-dev

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Disable tesseract multithreading for more scalable performance and
    # faster overall performance
    OMP_THREAD_LIMIT=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY doctor /opt/app/doctor
COPY manage.py /opt/app/
WORKDIR /opt/app

EXPOSE 5050

ARG options
ENV OPTIONS $options

CMD gunicorn $OPTIONS doctor.wsgi:application \
      --workers ${DOCTOR_WORKERS:-1} \
      --max-requests 1000 \
      --max-requests-jitter 100 \
      --timeout 5400 \
      --bind 0.0.0.0:5050
