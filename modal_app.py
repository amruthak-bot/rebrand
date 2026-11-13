"""Modal wrapper for ReBrand (deployed as app "rebrand" on Modal). Runs the unchanged FastAPI app as one always-warm container.

Deploy only after the owner says go and has logged in to Modal himself:  modal deploy modal_app.py
Local import test (no account needed):  python -c "import modal_app"

Design choices:
- max_containers=1: SQLite has one writer. Do not raise this.
- min_containers=1: no cold start for judges (this is what costs credits, roughly $2-4 for 72 h).
- Data lives on a Modal Volume mounted at /data. Volumes commit every few seconds and on shutdown,
  so a crash can lose the last few seconds. The demo story reloads on start if the DB is empty.
- Set a workspace budget in the Modal dashboard before deploying.
"""
import modal

APP_DIR = "/root/rebrand"
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libxcb1", "libglib2.0-0")  # system libs for opencv (RapidOCR)
    .pip_install("fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9", "pillow>=10.0",
                 "pypdf>=4.0", "rapidocr-onnxruntime>=1.3", "python-docx>=1.0")
    .env({"REBRAND_DB": "/data/rebrand.db", "REBRAND_AUTOSEED": "1", "REBRAND_DEMO_STORY": "1",
          "REBRAND_SCAN_HOURS": "24", "REBRAND_UPLOADS": "/data/uploads",
          "REBRAND_JOURNAL": "DELETE"})
    .add_local_dir("app", f"{APP_DIR}/app")
    .add_local_dir("static", f"{APP_DIR}/static")
)
volume = modal.Volume.from_name("rebrand-data", create_if_missing=True)
app = modal.App("rebrand", image=image)


@app.function(
    volumes={"/data": volume},
    min_containers=1,
    max_containers=1,
    cpu=1.0,
    memory=1024,
    scaledown_window=300,
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def web():
    import os
    import sys
    sys.path.insert(0, APP_DIR)
    os.makedirs("/data/uploads", exist_ok=True)
    from app import main as rebrand_main
    return rebrand_main.app
