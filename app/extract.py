"""Text extraction from uploaded guideline/content files."""
import io


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
        except Exception as e:
            raise ValueError(f"Could not extract text from PDF: {e}")
    if name.endswith(".docx"):
        try:
            import docx  # python-docx
            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs).strip()
        except ImportError:
            # minimal docx: XML inside a zip; strip tags
            import zipfile, re
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    xml = z.read("word/document.xml").decode("utf-8", errors="replace")
                xml = re.sub(r"</w:p>", "\n", xml)
                return re.sub(r"<[^>]+>", "", xml).strip()
            except Exception as e:
                raise ValueError(f"Could not extract text from DOCX: {e}")
        except Exception as e:
            raise ValueError(f"Could not extract text from DOCX: {e}")
    if name.endswith((".txt", ".md", ".text")) or "." not in name:
        return data.decode("utf-8", errors="replace").strip()
    # last resort: try utf-8
    try:
        return data.decode("utf-8", errors="replace").strip()
    except Exception:
        raise ValueError("Unsupported file type for text extraction")
