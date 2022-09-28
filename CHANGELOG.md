## Current

**0.2.16 - 2022-09-28**

Features:
 - Adds /utils/document-number/pdf/ service that returns the PACER document number from a RECAP PDF document.

## Previous Versions

**0.2.15 - 2022-07-27**

Fixes:
 - Adds PyCryptodome in order to handle encrypted PDFs ([144](https://github.com/freelawproject/doctor/issues/144))

**0.2.14 - 2022-07-26**

Features:
 - Adds sentry integration
 - Adds django-environ to allow environment variables for Django settings

**0.2.13 - 2022-06-02**

This release is focused on performance improvements and easier scaling. It:

 - Disables multi-threaded tesseract code. This makes it easier to scale doctor in a k8s environment due to at most one CPU being used per conversion.
 - Sets the number of gunicorn workers to 1 by default. This makes it so that scaling is can be moved to k8s instead of gunicorn.
 - Tells tesseract not to look for white text on black backgrounds. This is just a simple performance tweak.
 - Upgrades to PyPDF2 version 2.0.0.

**0.2.12 - 2022-05-19**

Features:
 - Add an even better encoding for extract_from_html

**0.2.11 - 2022-05-12**

Features:
 - Add even better encoding for extract_from_html
 - Add better error message

**0.2.10 - 2022-05-02**

Features:
 - Adds better encoding for extract_from_html
 - Bump seal-rookery to 2.2.1
 - Update seal-rookery call

**0.2.9 - 2022-04-19**

Features:
 - Fix for mime type detection for weird PDF failures
 - Test for broken PDFs

**0.2.8 - 2022-04-14**

Features:
 - Drop m1 specific docker builds.
 - Return 406's when validation of forms fails
 - Add tests for incomplete post requests to the server.
 - Reduce build installs and build install time.

**0.2.7 - 2022-04-12**

Features:
 - Bump seal-rookey to speed up builds.
 - Add m1 build in Makefile.

**0.2.6 - 2022-04-12**

Fixes:
 - Add additional workers and worker resets to the gunicorn configuration. The
   default is now four workers, and additional ones can be created with the
   DOCTOR_WORKERS env.

**0.2.5 - 2022-03-24**

Features:
 - Add two new endpoints
 - Extensions from blob
 - Mime type from blob

Changes:
 - Drop NGINX
 - Combine installation


**0.2.4 - 2022-03-23**

Features:
 - Refactor document/extract/ endpoint to return json and drop cookies

Changes:
 - Fix dockerfile update-seals
 - Drop cookie support and use JSON responses when necessary
 - Update tests
 - Update heartbeat to match disclosure endpoint

**0.2.3 - 2022-03-22**

Features:
 - Update type of response object
 - Drop json response success = False if invalid form and just return Bad Request

Changes:


**0.2.2 - 2022-03-21**

Features:
 - Split audio conversion into two steps: first convert to mp3
   and a second method to fetch audio duration..

Changes:
 - Update readme.
 - Bump version to 0.2.2
 - Update tests for new endpoint.


**0.2.1 - 2022-03-18**

Features:
 - Update nginx config for longer timeouts

Changes:
 - Update nginx config for longer timeouts
 - Bump python version for linting
 - Fix typo in DEVELOPING.md

**0.2.0 - 2022-03-16**

Features:
 - Greatly improved documentation
 - Improved speed

Changes:
 - Overhauled the entire codebase
 - Dropped seal-rookery image
 - Switched to Django and gunicorn from uWSGI and Flask
 - Completed api tests
 - Added Makefile for building and pushing
 - Updated NGINX config
 - Added DEVELOPING.md
 - Added composefile for testing with or without docker networking
 - Removed financial disclosures (coming soon as a separate project).
 - General improvements and cleanup.
 - Add support for multiple architectures. (linux/amd64,linux/arm64)
 - Added changelog


**0.1.0 - 2021-11-08**


**0.0.36 - 2021-05-11**


**0.0.36 - 2021-03-17**
