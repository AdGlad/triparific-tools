from __future__ import annotations

import io
import json
import os
import random
import string
from datetime import datetime
from typing import List, Tuple

from firebase_functions import https_fn
import firebase_admin
from google.cloud import storage
from PIL import Image, ImageOps


# ----------------------------------------------------------------------
# INITIALIZATION
# ----------------------------------------------------------------------

# Firebase Admin must be initialised exactly once
if not firebase_admin._apps:
    firebase_admin.initialize_app()

# Lazy-init storage client (avoids ADC import-time errors)
_storage_client: storage.Client | None = None

def get_storage_client() -> storage.Client:
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


# ----------------------------------------------------------------------
# CONFIGURATION (overridable via .env)
# ----------------------------------------------------------------------

CANVAS_WIDTH = 2000
CANVAS_HEIGHT = 2000
MIN_SCALE = 0.6
MAX_SCALE = 1.2
MAX_ROTATION_DEG = 25
AVOID_OVERLAP = True
OVERLAP_RETRIES = 15

STAMP_BUCKET = os.environ.get("STAMP_BUCKET")  # triparific100.appspot.com
STAMPS_PREFIX = os.environ.get("STAMPS_PREFIX", "passportStamps")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "passportStamps/composites")


def _require_bucket() -> str:
    if not STAMP_BUCKET:
        raise RuntimeError("STAMP_BUCKET env var not set")
    return STAMP_BUCKET


# ----------------------------------------------------------------------
# SIMPLE HEALTH-CHECK FUNCTION
# ----------------------------------------------------------------------

@https_fn.on_request()
def hello(req: https_fn.Request) -> https_fn.Response:
    return https_fn.Response(
        "Hello from Triparific Firebase Functions 👋",
        mimetype="text/plain",
        status=200,
    )


# ----------------------------------------------------------------------
# STAMP COMPOSITION HELPERS
# ----------------------------------------------------------------------

def _random_filename(prefix: str = "composite") -> str:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}_{ts}_{rand}.png"


def _random_transform(img: Image.Image) -> Image.Image:
    scale = random.uniform(MIN_SCALE, MAX_SCALE)
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    img_scaled = img.resize((new_w, new_h), Image.LANCZOS)

    angle = random.uniform(-MAX_ROTATION_DEG, MAX_ROTATION_DEG)
    return img_scaled.rotate(angle, resample=Image.BICUBIC, expand=True)


def _boxes_overlap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _choose_position(
    img_w: int,
    img_h: int,
    placed_boxes: List[Tuple[int, int, int, int]],
) -> Tuple[int, int]:
    retries = OVERLAP_RETRIES if AVOID_OVERLAP else 1

    for _ in range(retries):
        x = random.randint(0, max(0, CANVAS_WIDTH - img_w))
        y = random.randint(0, max(0, CANVAS_HEIGHT - img_h))
        candidate = (x, y, img_w, img_h)

        if not AVOID_OVERLAP or not any(_boxes_overlap(candidate, b) for b in placed_boxes):
            return x, y

    # fallback: accept overlap
    x = random.randint(0, max(0, CANVAS_WIDTH - img_w))
    y = random.randint(0, max(0, CANVAS_HEIGHT - img_h))
    return x, y


def _load_stamp_from_gcs(code: str) -> Image.Image | None:
    """Load bt_arrival.png etc from gs://bucket/passportStamps"""
    bucket_name = _require_bucket()
    bucket = get_storage_client().bucket(bucket_name)

    filename = f"{code.lower()}-arrival.png"   # <-- matches your real filenames
    blob_path = f"{STAMPS_PREFIX.rstrip('/')}/{filename}"
    blob = bucket.blob(blob_path)

    if not blob.exists():
        return None

    img_bytes = blob.download_as_bytes()
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    return ImageOps.contain(img, (img.width, img.height))


def _save_canvas_to_gcs(canvas: Image.Image, filename: str) -> str:
    bucket_name = _require_bucket()
    bucket = get_storage_client().bucket(bucket_name)

    blob_path = f"{OUTPUT_PREFIX.rstrip('/')}/{filename}"
    blob = bucket.blob(blob_path)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)

    blob.upload_from_file(buf, content_type="image/png")

    return f"gs://{bucket_name}/{blob_path}"


# ----------------------------------------------------------------------
# CORE COMPOSITION LOGIC
# ----------------------------------------------------------------------

def compose_passport_stamps(codes: List[str]) -> dict:
    codes = [c.lower() for c in codes if c]

    if not codes:
        raise ValueError("No country codes provided.")

    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    placed_boxes = []
    placed = []
    missing = []

    for code in codes:
        stamp = _load_stamp_from_gcs(code)

        if stamp is None:
            missing.append(code)
            continue

        transformed = _random_transform(stamp)
        x, y = _choose_position(transformed.width, transformed.height, placed_boxes)

        canvas.alpha_composite(transformed, dest=(x, y))
        placed_boxes.append((x, y, transformed.width, transformed.height))
        placed.append(code)

    if not placed:
        raise ValueError("No stamps found matching provided codes.")

    filename = _random_filename()
    gs_path = _save_canvas_to_gcs(canvas, filename)

    return {
        "filename": filename,
        "gs_path": gs_path,
        "placed": placed,
        "missing": missing,
    }


# ----------------------------------------------------------------------
# HTTP ENTRYPOINT
# ----------------------------------------------------------------------

@https_fn.on_request(region="us-central1", timeout_sec=300, memory=512)
def compose_passport_stamps_http(req: https_fn.Request) -> https_fn.Response:
    try:
        if req.method == "OPTIONS":
            return https_fn.Response("", status=204)

        codes = []

        # JSON POST
        if req.is_json:
            body = req.get_json(silent=True) or {}
            if isinstance(body.get("codes"), list):
                codes = [str(c) for c in body["codes"]]

        # GET ?codes=bt,au
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

        result = compose_passport_stamps(codes)

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

