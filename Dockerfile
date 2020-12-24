FROM python:3.8-slim

RUN apt-get update
RUN apt-get install -y --no-install-recommends \
        libatlas-base-dev gfortran nginx supervisor libpcre3 libpcre3-dev

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
         ffmpeg libmagic1 \
        `# Image & OCR tools` \
        imagemagick \
        `# Other dependencies` \
        libffi-dev libxml2-dev libxslt-dev python-dev

# Update and install depedencies
RUN apt-get update && \
    apt-get install -y wget unzip bc vim python3-pip libleptonica-dev git

# Packages to complie Tesseract
RUN apt-get install -y --reinstall make && \
    apt-get install -y g++ autoconf automake libtool pkg-config \
     libpng-dev libjpeg62-turbo-dev libtiff5-dev libicu-dev \
     libpango1.0-dev autoconf-archive

WORKDIR /tess

RUN mkdir src && cd /tess/src && \
    wget https://github.com/tesseract-ocr/tesseract/archive/4.1.1.zip && \
	unzip 4.1.1.zip && \
    cd /tess/src/tesseract-4.1.1 && ./autogen.sh && ./configure && make && make install && ldconfig && \
    make training && make training-install && \
    cd /usr/local/share/tessdata && wget https://github.com/tesseract-ocr/tessdata_best/raw/master/eng.traineddata

# Setting the data prefix
ENV TESSDATA_PREFIX=/usr/local/share/tessdata

RUN tesseract --version

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

RUN rm -rf /tess

CMD ["/usr/bin/supervisord"]

