"""Run: python tests/test_regressions.py. Isolated checks for the reported bugs."""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import extract, rules


def main():
    terms = [{"term": "guys", "kind": "banned", "replacement": "everyone", "note": ""}]
    assert not rules.check_terminology("Meet Guyson and his team.", terms)
    assert rules.check_terminology("Hey, GUYS!", terms)
    assert not rules._find_spans("anything", "")

    claims = [{"claim": "Used by teams in 12 countries", "expires_on": None}]
    issues, _ = rules.check_claims("Used by teams in 12 countries and we are the best in the world.", claims)
    assert any(i["rule_code"] == "CLAIM_UNSUPPORTED" for i in issues)
    assert not rules.check_claims("Used by teams in 12 countries.", claims)[0]
    assert not rules.check_claims("The best workshop", [{"claim": "The best workshop", "expires_on": None}])[0]
    issues, _ = rules.check_claims("Our software reduces operating costs by 87%.", claims)
    assert any(i["rule_code"] == "CLAIM_UNVERIFIED" and i["uncertain"] for i in issues)
    assert not rules.check_claims("Save 20% this week", [{"claim": "Save 20% this week", "expires_on": None}])[0]
    assert not rules.check_claims("Our workshop welcomed 12 participants.", claims)[0]

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hey gu</w:t></w:r><w:r><w:t>ys &amp; team!</w:t></w:r></w:p></w:body></w:document>')
    text = extract.extract_text("qa.docx", data.getvalue())
    assert text == "Hey guys & team!"
    assert rules.check_terminology(text, terms)
    assert extract.extract_text("qa.txt", b"plain text") == "plain text"
    try:
        extract.extract_text("broken.docx", b"not a document")
        raise AssertionError("Invalid DOCX was accepted")
    except ValueError:
        pass

    with tempfile.TemporaryDirectory() as directory:
        os.environ["REBRAND_DB"] = str(Path(directory) / "check.db")
        from app import main as server
        try:
            blueprint = {"terms": [], "claims": [], "guidelines": [], "palette": []}
            for kind in ("text", "document", "image"):
                issues, _, _ = server._run_checks({"text": "  ", "content_type": kind}, blueprint, [])
                assert any(i["rule_code"] == "CONTENT_MISSING" and i["severity"] == "high" for i in issues), kind
        finally:
            server.conn.close()
    print("PASS: whole terms, independent claims, percentage review, DOCX extraction and missing-content guards")


if __name__ == "__main__":
    main()
