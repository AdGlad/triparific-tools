from __future__ import annotations

import json
from typing import List

from firebase_functions import https_fn

from . import main


@https_fn.on_request(region="us-central1", timeout_sec=300, memory=512)
def compose_passport_stamps_http(req: https_fn.Request) -> https_fn.Response:
    """
    GET:
      /compose_passport_stamps_http?codes=au,ae,...

    POST JSON:
      { "codes": ["au","ae",...] }
    """
    try:
        if req.method == "OPTIONS":
            return https_fn.Response("", status=204)

        codes: List[str] = []

        if req.is_json:
            body = req.get_json(silent=True) or {}
            if isinstance(body.get("codes"), list):
                codes = [str(c) for c in body["codes"]]

        if not codes:
            param = req.args.get("codes")
            if param:
                codes = [c.strip() for c in param.split(",") if c.strip()]

        if not codes:
            return https_fn.Response(
                json.dumps({"ok": False, "error": "No country codes provided."}),
                mimetype="application/json",
                status=400,
            )

        result = main.compose_passport_stamps(codes)

        return https_fn.Response(
            json.dumps({"ok": True, **result}),
            mimetype="application/json",
            status=200,
        )

    except Exception as e:
        return https_fn.Response(
            json.dumps({"ok": False, "error": str(e)}),
            mimetype="application/json",
            status=500,
        )

