#!/usr/bin/env python3
import argparse, os, sys, math, datetime
from PIL import Image

def parse_args():
    p = argparse.ArgumentParser(description="Build a uniform 1:2 (h:w) grid of country flags.")
    p.add_argument("codes", nargs="+", help="2-char country codes (e.g., au nz us gb)")
    p.add_argument("--src-root", default="/Users/adglad/git/country-flags/png1000px",
                   help="Directory containing flag PNGs (1000px variants).")
    p.add_argument("--cols", type=int, default=8, help="Max flags per row (default: 8).")
    p.add_argument("--gap", type=int, default=12, help="Gap in pixels between tiles (default: 12).")
    p.add_argument("--tile-height", type=int, default=250,
                   help="Tile height in pixels (tile width = 2*height). Default 250 -> 500px wide.")
    p.add_argument("--bg", default="transparent",
                   help="Background color for the whole grid. 'transparent' (default) or #RRGGBB.")
    p.add_argument("--fit-mode", choices=["pad", "crop"], default="pad",
                   help="How to fit flags into the 1:2 tile. 'pad' preserves all content; 'crop' fills then center-crops.")
    return p.parse_args()

def hex_to_rgba(col):
    if col.lower() == "transparent":
        return None
    if col.startswith("#") and len(col) in (4, 7):
        if len(col) == 4:
            col = "#" + "".join([c*2 for c in col[1:]])
        r = int(col[1:3], 16); g = int(col[3:5], 16); b = int(col[5:7], 16)
        return (r, g, b, 255)
    return (255, 255, 255, 255)

def make_uniform_tile(img_path, box_h, ratio_w_over_h=2.0, fit_mode="pad"):
    """
    Returns an RGBA tile of size (box_w, box_h) where box_w = ratio * box_h.
    fit_mode:
      - 'pad': scale to fit entirely inside and center with transparent padding.
      - 'crop': scale to fill, then center-crop to exact size.
    """
    box_w = int(round(ratio_w_over_h * box_h))
    box_h = int(box_h)

    img = Image.open(img_path).convert("RGBA")
    w, h = img.size

    if fit_mode == "pad":
        # Scale to fit INSIDE box
        scale = min(box_w / w, box_h / h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        tile = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        x = (box_w - new_w) // 2
        y = (box_h - new_h) // 2
        tile.alpha_composite(img, (x, y))
        return tile

    # fit_mode == "crop": scale to FILL, then crop center
    scale = max(box_w / w, box_h / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center-crop to box_w x box_h
    left = max(0, (new_w - box_w) // 2)
    top = max(0, (new_h - box_h) // 2)
    right = left + box_w
    bottom = top + box_h
    cropped = img.crop((left, top, right, bottom))
    return cropped

def main():
    args = parse_args()
    codes = [c.strip().lower() for c in args.codes if c.strip()]
    if not codes:
        print("No country codes provided.", file=sys.stderr); sys.exit(1)

    missing, tiles = [], []
    for code in codes:
        path = os.path.join(args.src_root, f"{code}.png")
        if not os.path.isfile(path):
            missing.append(code); continue
        try:
            tile = make_uniform_tile(path, args.tile_height, ratio_w_over_h=2.0, fit_mode=args.fit_mode)
            tiles.append((code, tile))
        except Exception as e:
            missing.append(f"{code} (error: {e})")

    if not tiles:
        print("No images could be loaded. Check codes and src-root.", file=sys.stderr)
        if missing:
            print("Missing or failed:", ", ".join(missing), file=sys.stderr)
        sys.exit(2)
    if missing:
        print("Warning: missing flags for:", ", ".join(missing), file=sys.stderr)

    # Uniform tile size
    tile_w, tile_h = tiles[0][1].size

    cols = max(1, min(args.cols, len(tiles)))
    rows = math.ceil(len(tiles) / cols)
    gap = max(0, args.gap)

    canvas_w = cols * tile_w + (cols - 1) * gap
    canvas_h = rows * tile_h + (rows - 1) * gap

    bg_rgba = hex_to_rgba(args.bg)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0) if bg_rgba is None else bg_rgba)

    # Paste tiles
    for idx, (_, tile) in enumerate(tiles):
        r = idx // cols
        c = idx % cols
        x = c * (tile_w + gap)
        y = r * (tile_h + gap)
        canvas.alpha_composite(tile, (x, y))

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"/tmp/flags_grid_{ts}.png"

    if bg_rgba is None:
        canvas.save(out_path, format="PNG")
    else:
        canvas.convert("RGB").save(out_path, format="PNG")

    print(out_path)

if __name__ == "__main__":
    main()

