"""Optional OCR for image posts. Uses RapidOCR (PaddleOCR models on ONNX Runtime, CPU only,
no system binary). If the package is not installed the image checks still run without it."""
_engine = None
_tried = False


def available() -> bool:
    global _engine, _tried
    if not _tried:
        _tried = True
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        except Exception:
            _engine = None
    return _engine is not None


def read_text(data: bytes, min_conf: float = 0.5):
    """Return (text, lines). Lines below min_conf are ignored. Never raises."""
    if not available():
        return "", []
    try:
        import io
        from PIL import Image
        import numpy as np
        img = Image.open(io.BytesIO(data)).convert("RGB")
        res, _ = _engine(np.array(img))
        lines = [(t, float(c)) for _, t, c in (res or []) if float(c) >= min_conf]
        return "\n".join(t for t, _ in lines), lines
    except Exception:
        return "", []
