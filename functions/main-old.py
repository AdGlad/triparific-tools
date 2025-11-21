from __future__ import annotations

import io
import json
import os
import random
import string
from datetime import datetime
from typing import List, Tuple

from firebase_functions import https_fn
from firebase_admin import initialize_app
from google.cloud import storage
from PIL import Image, ImageOps

# --- Firebase / GCP init ---
app = initialize_app()
storage_client = storage.Client()

# --- Configuration ---
CANVAS_WIDTH = 2000
CANVAS_HEIGHT = 2000
MIN_SCALE = 0.6
MAX_SCALE = 1.2
MAX_ROTATION_DEG = 25
AVOID_OVERLAP = True
OVERLAP_RETRIES = 15

STAMP_BUCKET = os.environ.get("STAMP_BUCKET")  # e.g. triparific100.appspot.com
STAMPS_PREFIX = os.environ.get("STAMPS_PREFIX", "passportStamps")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "composites")


# === Helpers ===
def _random_filename(prefix: str = "stamps") -> str:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}_{ts}_{rand}.png"


def _random_transform(img: Image.Image) -> Image.Image:
    scale = random.uniform(MIN_SCALE, MAX_SCALE)
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    img_scaled = img.resize((new_w, new_h), Image.LANCZOS)

    angle = random.uniform(-MAX_ROTATION_DEG, MAX_ROTATION_DEG)
    img_rot = img_scaled.rotate(angle, resample=Image.BICUBIC, expand=True)
    return img_rot


def _boxes_overlap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw <= bx or
        bx + bw <= ax or
        ay + ah <= by or
        by + bh <= ay
    )


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
            return (x, y)

    return (
        random.randint(0, max(0, CANVAS_WIDTH - img_w)),
        random.randint(0, max(0, CANVAS_HEIGHT - img_h)),
    )

def _load_stamp_from_gcs(code: str) -> Image.Image | None:
    """Load a stamp image from Cloud Storage for the given country code."""
    bucket_name = _require_bucket()
    bucket = storage_client.bucket(bucket_name)
    # Matches bt_arrival.png, au_arrival.png, etc.
    filename = f"{code.lower()}_arrival.png"
    blob_path = f"{STAMPS_PREFIX.rstrip('/')}/{filename}"
    blob = bucket.blob(blob_path)

    if not blob.exists():
        return None

    img_bytes = blob.download_as_bytes()
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    img = ImageOps.contain(img, (img.width, img.height))
    return img


def _save_canvas_to_gcs(canvas: Image.Image, filename: str) -> str:
    if not STAMP_BUCKET:
        raise RuntimeError("STAMP_BUCKET env var not set")

    bucket = storage_client.bucket(STAMP_BUCKET)
    blob_path = f"{OUTPUT_PREFIX.rstrip('/')}/{filename}"
    blob = bucket.blob(blob_path)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    blob.upload_from_file(buf, content_type="image/png")

    return f"gs://{STAMP_BUCKET}/{blob_path}"


def compose_passport_stamps(codes: List[str]) -> dict:
    codes = [c.lower() for c in codes if c]
    if not codes:
        raise ValueError("No country codes provided.")

    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    placed_boxes: List[Tuple[int, int, int, int]] = []
    placed: List[str] = []
    missing: List[str] = []

    for code in codes:
        stamp = _load_stamp_from_gcs(code)
        if stamp is None:
            missing.append(code)
            continue

        stamp_t = _random_transform(stamp)
        x, y = _choose_position(stamp_t.width, stamp_t.height, placed_boxes)
        canvas.alpha_composite(stamp_t, dest=(x, y))
        placed_boxes.append((x, y, stamp_t.width, stamp_t.height))
        placed.append(code)

    if not placed:
        raise ValueError("No stamps placed. All missing or invalid codes.")

    filename = _random_filename()
    gs_path = _save_canvas_to_gcs(canvas, filename)

    return {
        "filename": filename,
        "gs_path": gs_path,
        "placed": placed,
        "missing": missing,
    }


@https_fn.on_request(region="australia-southeast1", timeout_sec=300, memory=512)
def compose_passport_stamps_http(req: https_fn.Request) -> https_fn.Response:
    try:
        if req.method == "OPTIONS":
            return https_fn.Response("", status=204)

        codes: List[str] = []

        if req.is_json:
            data = req.get_json(silent=True) or {}
            codes = data.get("codes") or []

        if not codes:
            codes_param = req.args.get("codes")
            if codes_param:
                codes = [c.strip() for c in codes_param.split(",") if c.strip()]

        if not codes:
            return https_fn.Response(
                json.dumps({"ok": False, "error": "No country codes provided."}),
                status=400,
                mimetype="application/json",
            )

        result = compose_passport_stamps(codes)
        return https_fn.Response(
            json.dumps({"ok": True, **result}),
            status=200,
            mimetype="application/json",
        )

    except Exception as e:
        return https_fn.Response(
            json.dumps({"ok": False, "error": str(e)}),
            status=500,
            mimetype="application/json",
        )
