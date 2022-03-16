#!/bin/bash
cd /opt
wget https://github.com/qpdf/qpdf/releases/download/release-qpdf-10.6.2/qpdf-10.6.2.tar.gz
tar -xf qpdf-10.6.2.tar.gz
cd /opt/qpdf-10.6.2/
./configure
make
make install
rm /opt/qpdf-10.6.2.tar.gz
rm -rf /opt/qpdf-10.6.2/
exec "$@"