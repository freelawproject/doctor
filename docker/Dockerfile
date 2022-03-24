FROM python:3.10-slim

RUN apt-get update --option "Acquire::Retries=3" --quiet=2 && \
    apt-get install -y --no-install-recommends apt-utils && \
    apt-get install -y python3-pip poppler-utils \
    wget unzip bc vim python3-pip libleptonica-dev git \
    tesseract-ocr libtesseract-dev \
    libatlas-base-dev gfortran supervisor libpcre3 libpcre3-dev \
    g++ libz-dev libjpeg-dev build-essential make && \
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

RUN pip install seal_rookery
RUN update-seals -f

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY doctor /opt/app/doctor
COPY manage.py /opt/app/
WORKDIR /opt/app

COPY docker/docker-entrypoint.sh /opt/app/
EXPOSE 5050
RUN ["chmod", "+x", "/opt/app/docker-entrypoint.sh"]
ENTRYPOINT ["/opt/app/docker-entrypoint.sh"]

