"""Deterministic rule engine. Every check returns issues with evidence, the
guideline clause behind it, a priority, and a suggestion. No model involved."""
import difflib
import datetime
import re

# Common promotional superlatives that require an approved claim source.
SUPERLATIVES = [
    "best in the world", "world's best", "world class", "world-class",
    "number one", "no. 1", "#1", "the best", "leading", "industry leading",
    "industry-leading", "unmatched", "unrivalled", "unrivaled", "revolutionary",
    "game-changing", "game changing", "cutting-edge", "cutting edge",
    "first ever", "first-ever", "guaranteed", "100%", "perfect", "ultimate",
]

WORD_RE = re.compile(r"[A-Za-z']+")


def _find_spans(text: str, needle: str):
    """Case-insensitive whole-phrase spans of needle in text."""
    spans = []
    if not needle:
        return spans
    for m in re.finditer(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", text, flags=re.IGNORECASE):
        spans.append((m.start(), m.end(), text[m.start():m.end()]))
    return spans


def _sentence(text: str, pos: int) -> str:
    start = max(text.rfind(".", 0, pos), text.rfind("\n", 0, pos)) + 1
    end = text.find(".", pos)
    if end == -1:
        end = min(len(text), pos + 160)
    else:
        end += 1
    return text[start:end].strip()


def _issue(rule_code, category, severity, evidence, clause, suggestion="", source="rule", uncertain=False):
    return {
        "rule_code": rule_code, "category": category, "severity": severity,
        "evidence": evidence, "clause": clause, "suggestion": suggestion,
        "source": source, "uncertain": 1 if uncertain else 0,
    }


def check_terminology(text: str, terms):
    issues = []
    for t in terms:
        if t["kind"] == "banned":
            for (s, e, found) in _find_spans(text, t["term"]):
                repl = t["replacement"] or "(remove)"
                issues.append(_issue(
                    "TERM_BANNED", "terminology", "high",
                    f"Found banned term \"{found}\" in: \"{_sentence(text, s)}\"",
                    f"Terminology rule: \"{t['term']}\" is not approved."
                    + (f" Note: {t['note']}" if t["note"] else ""),
                    f"Replace \"{found}\" with \"{repl}\".",
                ))
        elif t["kind"] == "preferred" and t["replacement"]:
            # preferred: 'term' is the discouraged wording, replacement is preferred
            for (s, e, found) in _find_spans(text, t["term"]):
                issues.append(_issue(
                    "TERM_PREFERRED", "terminology", "low",
                    f"Found non-preferred wording \"{found}\" in: \"{_sentence(text, s)}\"",
                    f"Terminology rule: prefer \"{t['replacement']}\" over \"{t['term']}\".",
                    f"Consider \"{t['replacement']}\" instead of \"{found}\".",
                ))
    return issues


def check_claims(text: str, claims):
    """Flag promotional claims that do not match the approved claim library.
    An approved claim present verbatim is recorded as a graph link, not an issue."""
    issues, used_claims = [], []
    today = datetime.date.today().isoformat()
    approved = [c["claim"] for c in claims if not c.get("expires_on") or c["expires_on"] >= today]
    approved_spans = [sp for a in approved for sp in _find_spans(text, a)]
    for c in claims:
        if c.get("expires_on") and c["expires_on"] < today and _find_spans(text, c["claim"]):
            issues.append(_issue(
                "CLAIM_EXPIRED", "claims", "high",
                f"Claim \"{c['claim']}\" expired on {c['expires_on']}.",
                "Claims rule: expired claims are not approved for publication.",
                "Remove this claim or replace it with a current approved claim."))
    # collect all superlative spans, then drop spans contained in a longer match
    raw_spans = []
    for s in SUPERLATIVES:
        raw_spans.extend(_find_spans(text, s))
    # longest first; keep a span only if it does not overlap an already-kept one
    raw_spans.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    spans = []
    for sp in raw_spans:
        if not any(sp[0] < o[1] and o[0] < sp[1] for o in spans):
            spans.append(sp)
    spans.sort(key=lambda x: x[0])
    for (st, en, found) in spans:
        sent = _sentence(text, st)
        if any(start <= st and en <= end for start, end, _ in approved_spans):
            continue
        # closest approved claim as suggestion (never invented)
        suggestion = "Remove the unsupported superlative, or replace it with an approved claim from the claim library."
        if approved:
            close = difflib.get_close_matches(sent, approved, n=1, cutoff=0.25)
            if close:
                suggestion = f"Replace with the approved claim: \"{close[0]}\", or remove the superlative."
        issues.append(_issue(
            "CLAIM_UNSUPPORTED", "claims", "high",
            f"Unsupported promotional claim \"{found}\" in: \"{sent}\"",
            "Claims rule: promotional claims must come from the approved claim library.",
            suggestion,
        ))
    # claims used verbatim anywhere (for Brand Validity Graph links)
    for a in approved:
        if _find_spans(text, a):
            used_claims.append(a)
    # Evidence debt: near-miss claims (claim-like wording close to, but not exactly, an approved claim)
    for a in approved:
        key = a.split()[0:3]
        if len(key) >= 2:
            probe = " ".join(key)
            for (st, en, found) in _find_spans(text, probe):
                sent = _sentence(text, st)
                if a.lower() not in sent.lower():
                    ratio = difflib.SequenceMatcher(None, sent.lower(), a.lower()).ratio()
                    if ratio > 0.45:
                        issues.append(_issue(
                            "CLAIM_NEAR_MISS", "claims", "medium",
                            f"Wording close to an approved claim but not exact: \"{sent}\"",
                            f"Claims rule: approved claim is \"{a}\". Near-exact wording still needs verification.",
                            f"Use the exact approved claim: \"{a}\".",
                            uncertain=True,
                        ))
                        break
    # ponytail: percentages are a heuristic, not fact-checking; expand patterns after testing real claim examples.
    known_spans = [sp for c in claims for sp in _find_spans(text, c["claim"])]
    for m in re.finditer(r"(?<!\w)\d+(?:[.,]\d+)*\s*%", text):
        if not any(start <= m.start() and m.end() <= end for start, end, _ in known_spans):
            issues.append(_issue(
                "CLAIM_UNVERIFIED", "claims", "medium",
                f"Percentage {m.group()} has no matching approved claim.",
                "Claims rule: numerical promotional claims need approved evidence.",
                "Verify the figure and its source with a reviewer before publishing.", uncertain=True))
    return issues, sorted(set(used_claims))


def check_headings(text: str):
    issues = []
    lines = [l for l in text.splitlines()]
    headings = [l for l in lines if l.strip().startswith("#")]
    if not headings and len(text) > 800:
        issues.append(_issue(
            "A11Y_HEADINGS", "accessibility", "low",
            "Long content with no heading structure detected.",
            "Accessibility rule: long content should use headings so assistive technology can navigate it.",
            "Add a clear heading structure (main heading, then section headings).",
        ))
    prev = 0
    for h in headings:
        level = len(h) - len(h.lstrip("#"))
        if prev and level > prev + 1:
            issues.append(_issue(
                "A11Y_HEADING_SKIP", "accessibility", "low",
                f"Heading level jumps from H{prev} to H{level}: \"{h.strip()[:60]}\"",
                "Accessibility rule: heading levels should not skip levels.",
                f"Use an H{prev+1} heading here instead.",
            ))
        prev = max(prev, level)
    return issues


def reading_level(text: str):
    words = WORD_RE.findall(text)
    if len(words) < 30:
        return None, None
    sentences = max(1, len(re.findall(r"[.!?]", text)))
    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in words)
    grade = 0.39 * (len(words) / sentences) + 11.8 * (syllables / len(words)) - 15.59
    return round(grade, 1), len(words)


def check_reading_level(text: str, max_grade: float = 12.0):
    grade, nwords = reading_level(text)
    if grade is None:
        return []
    if grade > max_grade:
        return [_issue(
            "A11Y_READING", "accessibility", "low",
            f"Estimated reading grade level {grade} across {nwords} words (target: grade {max_grade} or below).",
            "Accessibility rule: public content should be readable at a moderate grade level.",
            "Shorten sentences and prefer plain words. Split long sentences.",
        )]
    return []


def check_image(file_bytes: bytes, alt_text: str, blueprint, assets, images_mod):
    """Image checks per plan: asset hash match, palette vs approved palette, alt text."""
    issues, links = [], []
    sha = images_mod.sha256_bytes(file_bytes)
    asset_by_hash = {a["sha256"]: a for a in assets}
    if sha in asset_by_hash:
        a = asset_by_hash[sha]
        if a["active"]:
            links.append(("asset", a["name"]))
        else:
            issues.append(_issue(
                "ASSET_OUTDATED", "visual", "high",
                f"Image matches retired asset \"{a['name']}\" (sha256 {sha[:12]}...).",
                "Asset rule: only current approved asset versions may be used.",
                "Replace with the current approved version of this asset.",
            ))
    palette = images_mod.dominant_palette(file_bytes)
    approved = blueprint.get("palette") or []
    if approved:
        results = images_mod.palette_match(palette, approved)
        off = [r for r in results if not r["match"] and (r["share"] or 0) >= 0.05]
        for r in off:
            issues.append(_issue(
                "PALETTE_OFF_BRAND", "visual", "medium",
                f"Dominant colour {r['color']} (share {r['share']}) is not near any approved brand colour "
                f"(nearest approved {r['nearest_approved']}, distance {r['distance']}).",
                "Visual rule: dominant colours should come from the approved brand palette.",
                "Adjust the image colours toward the approved palette, or use an approved asset.",
            ))
    if not (alt_text or "").strip():
        issues.append(_issue(
            "A11Y_ALT_TEXT", "accessibility", "medium",
            "Image submitted without alt text.",
            "Accessibility rule: every published image needs descriptive alt text.",
            "Add a short description of what the image shows and its purpose.",
        ))
    return issues, links, sha, palette


def expired_claims(claims, today: str):
    """Claims past their expiry date still in the library."""
    out = []
    for c in claims:
        exp = c.get("expires_on")
        if exp and exp < today:
            out.append(c)
    return out
