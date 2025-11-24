from __future__ import annotations

import io
import json
import os
import random
import string
import math
from datetime import datetime
from typing import List, Tuple

from firebase_functions import https_fn
import firebase_admin
from google.cloud import storage
from PIL import Image, ImageOps


# ----------------------------------------------------------------------
# INITIALIZATION
# ----------------------------------------------------------------------

# Initialise Firebase Admin once
if not firebase_admin._apps:
    firebase_admin.initialize_app()

# Lazy-init Google Cloud Storage client
_storage_client: storage.Client | None = None


def get_storage_client() -> storage.Client:
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


# ----------------------------------------------------------------------
# CONFIGURATION VIA ENV
# ----------------------------------------------------------------------

# Stamps (passport stamps collage)
STAMP_BUCKET = os.environ.get("STAMP_BUCKET")  # e.g. triparific100.appspot.com
STAMPS_PREFIX = os.environ.get("STAMPS_PREFIX", "passportStamps")

# Flags (t-shirt flag grid)
FLAGS_PREFIX = os.environ.get("FLAGS_PREFIX", "flags/png1000px")
FLAGS_OUTPUT_PREFIX = os.environ.get("FLAGS_OUTPUT_PREFIX", "tshirt/flags")

# Shared image layout config
CANVAS_WIDTH = 2000
CANVAS_HEIGHT = 2000
MIN_SCALE = 0.6
MAX_SCALE = 1.2
MAX_ROTATION_DEG = 25
AVOID_OVERLAP = True
OVERLAP_RETRIES = 15


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
# SHARED HELPERS
# ----------------------------------------------------------------------

def _random_filename(prefix: str = "image") -> str:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}_{ts}_{rand}.png"


# ----------------------------------------------------------------------
# PASSPORT STAMP COMPOSITION
# ----------------------------------------------------------------------

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

    # Fallback: accept overlap
    x = random.randint(0, max(0, CANVAS_WIDTH - img_w))
    y = random.randint(0, max(0, CANVAS_HEIGHT - img_h))
    return x, y


def _load_stamp_from_gcs(code: str) -> Image.Image | None:
    """Load au-arrival.png etc from gs://bucket/passportStamps"""
    bucket_name = _require_bucket()
    bucket = get_storage_client().bucket(bucket_name)

    # Matches au-arrival.png, bt-arrival.png, etc.
    filename = f"{code.lower()}-arrival.png"
    blob_path = f"{STAMPS_PREFIX.rstrip('/')}/{filename}"
    blob = bucket.blob(blob_path)

    if not blob.exists():
        return None

    img_bytes = blob.download_as_bytes()
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    return ImageOps.contain(img, (img.width, img.height))


def _save_canvas_to_gcs(canvas: Image.Image, filename: str, output_prefix: str) -> str:
    bucket_name = _require_bucket()
    bucket = get_storage_client().bucket(bucket_name)

    blob_path = f"{output_prefix.rstrip('/')}/{filename}"
    blob = bucket.blob(blob_path)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    blob.upload_from_file(buf, content_type="image/png")

    return f"gs://{bucket_name}/{blob_path}"


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

        transformed = _random_transform(stamp)
        x, y = _choose_position(transformed.width, transformed.height, placed_boxes)

        canvas.alpha_composite(transformed, dest=(x, y))
        placed_boxes.append((x, y, transformed.width, transformed.height))
        placed.append(code)

    if not placed:
        raise ValueError("No stamps found matching provided codes.")

    filename = _random_filename(prefix="stamps")
    gs_path = _save_canvas_to_gcs(canvas, filename, FLAGS_OUTPUT_PREFIX)

    return {
        "filename": filename,
        "gs_path": gs_path,
        "placed": placed,
        "missing": missing,
    }


# ----------------------------------------------------------------------
# FLAG GRID (1:2 RATIO) – FROM flag_grid_12ratio_fit1.py
# ----------------------------------------------------------------------

def hex_to_rgba(col: str) -> Tuple[int, int, int, int] | None:
    if col.lower() == "transparent":
        return None
    if col.startswith("#") and len(col) in (4, 7):
        if len(col) == 4:
            col = "#" + "".join([c * 2 for c in col[1:]])
        r = int(col[1:3], 16)
        g = int(col[3:5], 16)
        b = int(col[5:7], 16)
        return (r, g, b, 255)
    return (255, 255, 255, 255)


def make_uniform_tile_from_bytes(
    img_bytes: bytes,
    box_h: int,
    ratio_w_over_h: float = 2.0,
    fit_mode: str = "pad",
) -> Image.Image:
    """
    Returns an RGBA tile of size (box_w, box_h) where box_w = ratio * box_h.
    """
    box_w = int(round(ratio_w_over_h * box_h))
    box_h = int(box_h)

    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    w, h = img.size

    if fit_mode == "pad":
        scale = min(box_w / w, box_h / h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        tile = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        x = (box_w - new_w) // 2
        y = (box_h - new_h) // 2
        tile.alpha_composite(img, (x, y))
        return tile

    if fit_mode == "crop":
        scale = max(box_w / w, box_h / h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = max(0, (new_w - box_w) // 2)
        top = max(0, (new_h - box_h) // 2)
        right = left + box_w
        bottom = top + box_h
        return img.crop((left, top, right, bottom))

    # fit_mode == "stretch"
    return img.resize((box_w, box_h), Image.LANCZOS)


def _load_flag_tile_from_gcs(
    code: str,
    tile_height: int,
    fit_mode: str,
) -> Image.Image | None:
    """
    Load a flag PNG (code.png) from FLAGS_PREFIX and build a 1:2 tile.
    """
    bucket_name = _require_bucket()
    bucket = get_storage_client().bucket(bucket_name)

    flag_filename = f"{code.lower()}.png"
    blob_path = f"{FLAGS_PREFIX.rstrip('/')}/{flag_filename}"
    blob = bucket.blob(blob_path)

    if not blob.exists():
        return None

    img_bytes = blob.download_as_bytes()
    return make_uniform_tile_from_bytes(
        img_bytes, tile_height, ratio_w_over_h=2.0, fit_mode=fit_mode
    )


def build_flag_grid(
    codes: List[str],
    cols: int = 8,
    gap: int = 12,
    tile_height: int = 250,
    bg: str = "transparent",
    fit_mode: str = "pad",
) -> dict:
    """
    Build a grid of flags (1:2 ratio tiles) and upload to FLAGS_OUTPUT_PREFIX.
    """
    codes = [c.strip().lower() for c in codes if c.strip()]
    if not codes:
        raise ValueError("No country codes provided.")

    missing: List[str] = []
    tiles: List[Tuple[str, Image.Image]] = []

    for code in codes:
        tile = _load_flag_tile_from_gcs(code, tile_height, fit_mode)
        if tile is None:
            missing.append(code)
            continue
        tiles.append((code, tile))

    if not tiles:
        raise ValueError("No images could be loaded. Check codes and FLAGS_PREFIX.")

    # Grid geometry
    tile_w, tile_h = tiles[0][1].size
    cols = max(1, min(cols, len(tiles)))
    rows = math.ceil(len(tiles) / cols)
    gap = max(0, gap)

    canvas_w = cols * tile_w + (cols - 1) * gap
    canvas_h = rows * tile_h + (rows - 1) * gap

    bg_rgba = hex_to_rgba(bg)
    canvas = Image.new(
        "RGBA",
        (canvas_w, canvas_h),
        (0, 0, 0, 0) if bg_rgba is None else bg_rgba,
    )

    for idx, (_, tile) in enumerate(tiles):
        r = idx // cols
        c = idx % cols
        x = c * (tile_w + gap)
        y = r * (tile_h + gap)
        canvas.alpha_composite(tile, (x, y))

    filename = _random_filename(prefix="flags")

    # If background is transparent, keep RGBA. Otherwise, convert to RGB.
    if bg_rgba is None:
        gs_path = _save_canvas_to_gcs(canvas, filename, FLAGS_OUTPUT_PREFIX)
    else:
        rgb_canvas = canvas.convert("RGB")
        gs_path = _save_canvas_to_gcs(rgb_canvas, filename, FLAGS_OUTPUT_PREFIX)

    placed_codes = [code for code, _ in tiles]

    return {
        "filename": filename,
        "gs_path": gs_path,
        "placed": placed_codes,
        "missing": missing,
    }


# Re-export HTTP handlers defined in separate modules for deployment entrypoints.
from .compose_passport_stamps_http import compose_passport_stamps_http  # noqa: E402,F401
from .flag_grid_http import flag_grid_http  # noqa: E402,F401
