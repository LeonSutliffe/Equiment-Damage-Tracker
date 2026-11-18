"""Run the web application with Waitress on 127.0.0.1 (Caddy sits in front).

Used by the Windows service. Run by hand with:  python serve.py
"""

import os

from waitress import serve

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "faults.settings")

from faults.wsgi import application  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("FAULTS_PORT", "8000"))
    print(f"Equipment Damage Tracker listening on http://127.0.0.1:{port}")
    serve(
        application,
        host="127.0.0.1",
        port=port,
        threads=8,
        trusted_proxy="127.0.0.1",
        trusted_proxy_headers={"x-forwarded-proto", "x-forwarded-for", "x-forwarded-host"},
        clear_untrusted_proxy_headers=True,
        max_request_body_size=200 * 1024 * 1024,
    )
