# Settings for public access via an HTTPS tunnel (e.g. trycloudflare.com).
#
# Inherits everything from production and only adds the CSRF trusted origins
# that Django requires when POST requests arrive from a different origin than
# the one the backend sees (the tunnel terminates HTTPS and forwards plain
# HTTP to Traefik).

from .production import *  # pylint: disable=wildcard-import

# Wildcard domains are supported by Django >= 4.0.
# Override with the CVAT_CSRF_TRUSTED_ORIGINS env variable (comma-separated,
# scheme included, e.g. "https://*.trycloudflare.com,https://cvat.example.com").
CSRF_TRUSTED_ORIGINS = os.getenv(
    "CVAT_CSRF_TRUSTED_ORIGINS", "https://*.trycloudflare.com"
).split(",")
