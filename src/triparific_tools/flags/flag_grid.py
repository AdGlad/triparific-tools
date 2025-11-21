#!/usr/bin/env python3
import argparse, os, sys, math, datetime
from PIL import Image

def parse_args():
    p = argparse.ArgumentParser(description="Build a grid of country flags.")
    p.add_argument("codes", nargs="+", help="2-char country codes (e.g., au nz us gb)")
    p.add_argument("--src-root", default="/Users/adglad/git/country-flags/png1000px",
                   help="Directory containing flag PNGs (1000px variants).")
    p.add_argument("--cols", type=int, default=8, help="Max flags per row (default: 8).")
    p.add_argument("--gap", type=int, default=12, help="Gap in pixels between flags (default: 12).")
    p.add_argument("--scale-height", type=int, default=250,
                   help="Target height for each flag while preserving aspect ratio (default: 250).")
    p.add_argument("--bg", default="#FFFFFF",
                   help="Background color, e.g. #FFFFFF or 'transparent'. Default white.")
    return p.parse_args()

def load_and_scale(img_path, target_h):
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    if h != target_h:
        new_w = int(round(w * (target_h / h)))
        img = img.resize((new_w, target_h), Image.LANCZOS)
    return img

def main():
    args = parse_args()
    codes = [c.strip().lower() for c in args.codes if c.strip()]
    if not codes:
        print("No country codes provided.", file=sys.stderr); sys.exit(1)

    # Resolve files (expecting filenames like 'au.png', 'cl.png', etc.)
    missing = []
    images = []
    for code in codes:
        path = os.path.join(args.src_root, f"{code}.png")
        if not os.path.isfile(path):
            missing.append(code)
            continue
        try:
            images.append((code, load_and_scale(path, args.scale_height)))
        except Exception as e:
            missing.append(f"{code} (error: {e})")

    if not images:
        print("No images could be loaded. Check codes and src-root.", file=sys.stderr)
        if missing:
            print("Missing or failed:", ", ".join(missing), file=sys.stderr)
        sys.exit(2)

    if missing:
        print("Warning: missing flags for:", ", ".join(missing), file=sys.stderr)

    cols = max(1, min(args.cols, len(images)))
    rows = math.ceil(len(images) / cols)
    gap = max(0, args.gap)

    # Compute canvas width per row (variable widths because flags vary)
    row_widths = []
    row_heights = []
    for r in range(rows):
        row_imgs = images[r*cols:(r+1)*cols]
        row_w = sum(im.size[0] for _, im in row_imgs) + gap * (len(row_imgs) - 1 if len(row_imgs) > 1 else 0)
        row_h = max(im.size[1] for _, im in row_imgs)
        row_widths.append(row_w)
        row_heights.append(row_h)

    canvas_w = max(row_widths)
    canvas_h = sum(row_heights) + gap * (rows - 1 if rows > 1 else 0)

    # Background
    if args.bg.lower() == "transparent":
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    else:
        # Convert hex to RGB
        col = args.bg
        if col.startswith("#") and len(col) in (4, 7):
            if len(col) == 4:
                col = "#" + "".join([c*2 for c in col[1:]])
            r = int(col[1:3], 16); g = int(col[3:5], 16); b = int(col[5:7], 16)
            bg = (r, g, b, 255)
        else:
            # Fallback to white if parsing fails
            bg = (255, 255, 255, 255)
        canvas = Image.new("RGBA", (canvas_w, canvas_h), bg)

    # Paste images
    y = 0
    for r in range(rows):
        row_imgs = images[r*cols:(r+1)*cols]
        row_h = row_heights[r]
        # left-align; could center by computing leftover = canvas_w - row_widths[r]
        x = 0
        for code, im in row_imgs:
            # vertically top-aligned; to center: y + (row_h - im.height)//2
            canvas.alpha_composite(im, (x, y))
            x += im.size[0] + gap
        y += row_h + (gap if r < rows - 1 else 0)

    # Save to /tmp with timestamp
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"/tmp/flags_grid_{ts}.png"
    # Convert to RGB if background isn’t transparent (smaller file)
    if args.bg.lower() == "transparent":
        canvas.save(out_path, format="PNG")
    else:
        canvas.convert("RGB").save(out_path, format="PNG")

    print(out_path)

if __name__ == "__main__":
    main()

