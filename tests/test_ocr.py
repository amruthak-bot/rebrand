"""OCR on an image post. Needs: pip install -r requirements-ocr.txt. Fresh seeded db, server on :8000."""
import io, sys
sys.path.insert(0, "tests")
from test_e2e import call
from PIL import Image, ImageDraw, ImageFont
import glob
font = glob.glob('/usr/share/fonts/**/*.ttf', recursive=True)[0]
im = Image.new("RGB", (900, 260), (24, 87, 63)); d = ImageDraw.Draw(im)
d.text((40, 40), "Hey guys! We are the best in the world.", font=ImageFont.truetype(font, 34), fill="white")
d.text((40, 120), "Winter launch with synergy for everyone", font=ImageFont.truetype(font, 30), fill="white")
buf = io.BytesIO(); im.save(buf, "PNG")
cr = call("POST", "/api/login", body={"email": "creator@demo.test", "password": "creator123"})["token"]
sid = call("POST", "/api/submissions", token=cr, body={"title": "Ad image", "content_type": "image", "channel": "social", "alt_text": "Green ad banner"})["id"]
call("POST", f"/api/submissions/{sid}/upload", token=cr, form={"file": ("ad.png", buf.getvalue(), "image/png")})
r = call("POST", f"/api/submissions/{sid}/check", token=cr)
ocr_hits = [i for i in r["issues"] if "OCR" in i["evidence"]]
codes = {i["rule_code"] for i in ocr_hits}
assert "TERM_BANNED" in codes, r["issues"]
print("OCR: banned words inside the image were found:", sorted(codes))
