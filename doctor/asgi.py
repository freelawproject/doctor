"""
WSGI config for doctor project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/howto/deployment/wsgi/
"""

import os

from django.core.asgi import get_asgi_application

from doctor.middleware import GatekeeperMiddleware

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doctor.settings")

application = GatekeeperMiddleware(get_asgi_application())
