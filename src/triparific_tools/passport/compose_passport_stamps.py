#!/usr/bin/env python3
import os
import sys
import random
import string
from datetime import datetime
from typing import List
from PIL import Image, ImageOps

# === Configuration ===
STAMPS_DIR = "/Users/adglad/triparific/stamps/arrival/"
OUTPUT_DIR = "/Users/adglad/triparific/stamps/temp/"
CANVAS_WIDTH = 2000
CANVAS_HEIGHT = 2000
MIN_SCALE = 0.6
MAX_SCALE = 1.2
MAX_ROTATION_DEG = 25
AVOID_OVERLAP = True
OVERLAP_RETRIES = 15


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


def _boxes_overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _choose_position(img_w: int, img_h: int, placed_boxes: List[tuple]) -> tuple:
    for _ in range(OVERLAP_RETRIES if AVOID_OVERLAP else 1):
        x = random.randint(0, max(0, CANVAS_WIDTH - img_w))
        y = random.randint(0, max(0, CANVAS_HEIGHT - img_h))
        candidate = (x, y, img_w, img_h)
        if not AVOID_OVERLAP or not any(_boxes_overlap(candidate, b) for b in placed_boxes):
            return (x, y)
    return (random.randint(0, max(0, CANVAS_WIDTH - img_w)),
            random.randint(0, max(0, CANVAS_HEIGHT - img_h)))


# === Main function ===
def compose_passport_stamps_local(codes: List[str]) -> str:
    codes = [c.lower() for c in codes if c]
    if not codes:
        print("⚠️  No country codes provided.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    placed_boxes = []
    placed = []
    missing = []

    for code in codes:
        filename = f"{code}-arrival.png"
        filepath = os.path.join(STAMPS_DIR, filename)

        if not os.path.exists(filepath):
            missing.append(code)
            continue

        stamp = Image.open(filepath).convert("RGBA")
        stamp = ImageOps.contain(stamp, (stamp.width, stamp.height))
        stamp_t = _random_transform(stamp)
        x, y = _choose_position(stamp_t.width, stamp_t.height, placed_boxes)
        canvas.alpha_composite(stamp_t, dest=(x, y))
        placed_boxes.append((x, y, stamp_t.width, stamp_t.height))
        placed.append(code)

    if not placed:
        print("⚠️ No stamps placed. All missing or invalid codes.")
        sys.exit(1)

    output_filename = _random_filename()
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    canvas.save(output_path, "PNG")

    print("✅ Composite image created!")
    print(f"📄 Output: {output_path}")
    print(f"✅ Placed stamps: {placed}")
    if missing:
        print(f"⚠️ Missing stamps: {missing}")
    return output_path


# === CLI entrypoint ===
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 compose_passport_stamps_local.py <country_code> [<country_code> ...]")
        print("Example: python3 compose_passport_stamps_local.py au ae tr gr it fr es")
        sys.exit(1)

    country_codes = sys.argv[1:]
    compose_passport_stamps_local(country_codes)

