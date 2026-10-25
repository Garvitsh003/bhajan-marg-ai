from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_weak_evidence_notice_has_localized_explicit_boundaries():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'message.evidence_level === "none" || message.evidence_level === "related"' in js
    assert "not a direct statement from Premanand Ji" in js
    assert "प्रेमानंद जी का सीधा कथन न मानें" in js
    assert "directly answer your exact question" in js
