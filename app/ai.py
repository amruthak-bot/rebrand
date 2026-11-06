"""Optional AI tone/messaging layer. Works only when REBRAND_LLM_KEY is set.
Without a key the check is reported as Uncertain and routed to a human,
exactly as the plan requires: the product must work without a key."""
import json
import os
import urllib.request


def configured() -> bool:
    return bool(os.environ.get("REBRAND_LLM_KEY"))


def tone_check(text: str, blueprint):
    """Return (issues, note). Grounded only in blueprint excerpts."""
    if not configured():
        return [], "AI tone check not run: no model key configured. Marked for human review (Uncertain)."
    guidelines = "\n".join(g["body"][:600] for g in blueprint.get("guidelines", [])[:4])
    prompt = (
        "You are checking a draft against an organisation's brand guidelines.\n"
        "Only flag an issue if you can quote the exact guideline clause it violates.\n"
        "Return JSON: [{\"clause\": \"...\", \"evidence\": \"...\", \"suggestion\": \"...\"}]\n\n"
        f"GUIDELINES:\n{guidelines}\n\nDRAFT:\n{text[:4000]}"
    )
    try:
        base = os.environ.get("REBRAND_LLM_BASE", "https://api.openai.com/v1")
        model = os.environ.get("REBRAND_LLM_MODEL", "gpt-4o-mini")
        req = urllib.request.Request(
            base.rstrip("/") + "/chat/completions",
            data=json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }).encode(),
            headers={
                "Authorization": "Bearer " + os.environ["REBRAND_LLM_KEY"],
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
        content = body["choices"][0]["message"]["content"]
        start, end = content.find("["), content.rfind("]")
        items = json.loads(content[start:end + 1]) if start != -1 else []
        issues = []
        for it in items[:10]:
            clause = (it.get("clause") or "").strip()
            if not clause or clause.lower() not in guidelines.lower():
                # uncited output is marked Uncertain, never passed silently
                issues.append({
                    "rule_code": "AI_TONE", "category": "tone", "severity": "medium",
                    "evidence": (it.get("evidence") or "AI tone finding")[:400],
                    "clause": clause or "No guideline clause cited",
                    "suggestion": (it.get("suggestion") or "")[:400],
                    "source": "ai", "uncertain": 1,
                })
            else:
                issues.append({
                    "rule_code": "AI_TONE", "category": "tone", "severity": "medium",
                    "evidence": (it.get("evidence") or "")[:400],
                    "clause": clause[:400],
                    "suggestion": (it.get("suggestion") or "")[:400],
                    "source": "ai", "uncertain": 0,
                })
        return issues, "AI tone check ran with blueprint grounding. AI-assisted suggestions are disclosed."
    except Exception as e:
        return [], f"AI tone check failed ({e}). Marked for human review (Uncertain)."
