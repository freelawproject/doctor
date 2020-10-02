FROM python:3.7

RUN apt-get update
RUN apt-get install -y --no-install-recommends \
        libatlas-base-dev gfortran nginx supervisor

RUN apt-get update --option "Acquire::Retries=3" --quiet=2 && \
    apt-get install -y --no-install-recommends apt-utils && \
    apt-get install \
        --option "Acquire::Retries=3" \
        --no-install-recommends \
        --assume-yes \
        --quiet=2 \
        `# Document extraction and OCR tools` \
        antiword docx2txt ghostscript libwpd-tools poppler-utils \
        `# Audio extraction/manipulation tools` \
         ffmpeg \
        `# Image & OCR tools` \
        imagemagick tesseract-ocr tesseract-ocr-eng \
        `# Other dependencies` \
        libffi-dev libxml2-dev libxslt-dev python-dev


RUN pip install uwsgi

COPY ./requirements-docker.txt /project/requirements.txt

RUN pip install -r /project/requirements.txt

RUN useradd --no-create-home nginx

RUN rm /etc/nginx/sites-enabled/default
RUN rm -r /root/.cache

COPY server-conf/nginx.conf /etc/nginx/
COPY server-conf/flask-site-nginx.conf /etc/nginx/conf.d/
COPY server-conf/uwsgi.ini /etc/uwsgi/
COPY server-conf/supervisord.conf /etc/supervisor/

COPY src /project/src

WORKDIR /project

CMD ["/usr/bin/supervisord"]

