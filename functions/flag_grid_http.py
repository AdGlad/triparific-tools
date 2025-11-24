from __future__ import annotations

import json
from typing import List

from firebase_functions import https_fn

from . import main


@https_fn.on_request(region="us-central1", timeout_sec=300, memory=512)
def flag_grid_http(req: https_fn.Request) -> https_fn.Response:
    """
    Build a 1:2 ratio grid of flags and upload to FLAGS_OUTPUT_PREFIX.

    GET example:
      /flag_grid_http?codes=au,ae,tr,gr&fit_mode=pad&bg=transparent

    POST JSON:
      {
        "codes": ["au","ae","tr","gr","al","me","ba","hr","at","sk","pl","cz","de","nl","be","it","fr","es","pt","gb","xk"],
        "cols": 8,
        "gap": 12,
        "tile_height": 250,
        "bg": "transparent",
        "fit_mode": "pad"
      }
    """
    try:
        if req.method == "OPTIONS":
            return https_fn.Response("", status=204)

        data = {}
        codes: List[str] = []

        if req.is_json:
            data = req.get_json(silent=True) or {}
            if isinstance(data.get("codes"), list):
                codes = [str(c) for c in data["codes"]]

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

        cols = int(data.get("cols", req.args.get("cols", 8)))
        gap = int(data.get("gap", req.args.get("gap", 12)))
        tile_height = int(data.get("tile_height", req.args.get("tile_height", 250)))
        bg = data.get("bg", req.args.get("bg", "transparent"))
        fit_mode = data.get("fit_mode", req.args.get("fit_mode", "pad"))

        result = main.build_flag_grid(
            codes=codes,
            cols=cols,
            gap=gap,
            tile_height=tile_height,
            bg=bg,
            fit_mode=fit_mode,
        )

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

