"""Image checks: sha256 identity, dominant palette, palette distance. Pillow only."""
import hashlib
import io
import json


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def dominant_palette(data: bytes, n: int = 5):
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((128, 128))
    q = img.quantize(colors=n, method=2)
    pal = q.getpalette()[: n * 3]
    colors = []
    counts = sorted(q.getcolors(), reverse=True)
    for count, idx in counts:
        r, g, b = pal[idx * 3: idx * 3 + 3]
        colors.append({"hex": "#%02x%02x%02x" % (r, g, b), "share": round(count / (img.width * img.height), 3)})
    return colors


def color_distance(c1, c2) -> float:
    return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5


def palette_match(palette_hexes, approved_hexes, tolerance: float = 60.0):
    """Return list of {color, approved, distance, match} for each dominant color."""
    out = []
    for c in palette_hexes:
        rgb = hex_to_rgb(c["hex"] if isinstance(c, dict) else c)
        best, best_d = None, 1e9
        for a in approved_hexes:
            d = color_distance(rgb, hex_to_rgb(a))
            if d < best_d:
                best, best_d = a, d
        out.append({
            "color": c["hex"] if isinstance(c, dict) else c,
            "share": c.get("share") if isinstance(c, dict) else None,
            "nearest_approved": best,
            "distance": round(best_d, 1),
            "match": best_d <= tolerance,
        })
    return out


def contrast_ratio(hex1: str, hex2: str) -> float:
    def lum(h):
        def chan(v):
            v = v / 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = hex_to_rgb(h)
        return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)
    l1, l2 = lum(hex1), lum(hex2)
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def palette_json(colors) -> str:
    return json.dumps(colors)
