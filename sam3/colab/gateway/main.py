# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Multiplexing Nuclio-gateway shim for CVAT.

Sits between CVAT's lambda_manager and the local Nuclio dashboard:

    cvat_server -> [this gateway] -> http://nuclio:8070        (local functions)
                                -> https://<colab-tunnel>     (SAM 3 on Google Colab)

Endpoints served (Nuclio dashboard compatible):
    GET  /api/functions                 merged function list
    GET  /api/functions/<id>            single function
    POST /api/function_invocations      proxied to local Nuclio or Colab
"""

import os

import requests
from flask import Flask, Response, jsonify, request

LOCAL_NUCLIO_URL = os.environ.get("LOCAL_NUCLIO_URL", "http://nuclio:8070").rstrip("/")
COLAB_FUNCTION_URL = os.environ.get("COLAB_FUNCTION_URL", "").rstrip("/")
COLAB_FUNCTION_ID = os.environ.get(
    "COLAB_FUNCTION_ID", "pth-facebookresearch-sam3-colab"
)

LOCAL_TIMEOUT = int(os.environ.get("LOCAL_TIMEOUT", "30"))
COLAB_TIMEOUT = int(os.environ.get("COLAB_TIMEOUT", "300"))

app = Flask(__name__)


def _proxied_response(reply: requests.Response) -> Response:
    return Response(
        reply.content,
        status=reply.status_code,
        content_type=reply.headers.get("content-type", "application/json"),
    )


@app.get("/api/functions")
def list_functions():
    merged = {}

    if COLAB_FUNCTION_URL:
        try:
            reply = requests.get(f"{COLAB_FUNCTION_URL}/api/functions", timeout=COLAB_TIMEOUT)
            reply.raise_for_status()
            merged.update(reply.json())
        except Exception as exc:  # noqa: BLE001
            app.logger.error("Failed to fetch functions from Colab: %s", exc)

    try:
        reply = requests.get(f"{LOCAL_NUCLIO_URL}/api/functions", timeout=LOCAL_TIMEOUT)
        reply.raise_for_status()
        merged.update(reply.json())  # local entries win on id collisions
    except Exception as exc:  # noqa: BLE001
        app.logger.error("Failed to fetch functions from local Nuclio: %s", exc)

    return jsonify(merged)


@app.get("/api/functions/<func_id>")
def get_function(func_id: str):
    if func_id == COLAB_FUNCTION_ID and COLAB_FUNCTION_URL:
        reply = requests.get(
            f"{COLAB_FUNCTION_URL}/api/functions/{func_id}", timeout=COLAB_TIMEOUT
        )
        return _proxied_response(reply)

    reply = requests.get(f"{LOCAL_NUCLIO_URL}/api/functions/{func_id}", timeout=LOCAL_TIMEOUT)
    return _proxied_response(reply)


@app.route("/api/function_invocations", methods=["POST"])
def invoke_function():
    func_name = request.headers.get("x-nuclio-function-name", "")
    headers = {
        "x-nuclio-function-name": func_name,
        "x-nuclio-path": request.headers.get("x-nuclio-path", "/"),
    }

    if func_name == COLAB_FUNCTION_ID and COLAB_FUNCTION_URL:
        target = f"{COLAB_FUNCTION_URL}/api/function_invocations"
        timeout = COLAB_TIMEOUT
    else:
        target = f"{LOCAL_NUCLIO_URL}/api/function_invocations"
        timeout = LOCAL_TIMEOUT

    try:
        reply = requests.post(target, headers=headers, json=request.get_json(force=True), timeout=timeout)
    except requests.Timeout as exc:
        app.logger.error("Invocation of %s timed out: %s", func_name, exc)
        return jsonify({"error": "function invocation timed out"}), 504
    except requests.RequestException as exc:
        app.logger.error("Invocation of %s failed: %s", func_name, exc)
        return jsonify({"error": f"function invocation failed: {exc}"}), 502

    return _proxied_response(reply)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8070")), threaded=True)
