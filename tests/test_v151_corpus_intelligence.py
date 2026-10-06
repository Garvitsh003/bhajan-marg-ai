import json

from app.corpus_intelligence import _bucketize_sections, make_search_text
from app.query_intent import intent_to_queries


def test_temporal_map_expands_sections_to_ten_second_buckets():
    buckets = _bucketize_sections(
        [{
            "start_ms": 12_000,
            "end_ms": 35_000,
            "topics": ["प्रेम"],
            "situations": ["एकतरफा प्रेम"],
            "intents": ["क्या करना चाहिए"],
            "concepts": ["आसक्ति"],
            "summary": "प्रेम और आसक्ति की चर्चा",
        }],
        duration_ms=50_000,
    )

    assert [x["start_ms"] for x in buckets] == [10_000, 20_000, 30_000]
    assert all("प्रेम" in x["topics"] for x in buckets)


def test_search_text_puts_title_and_semantics_before_transcript():
    value = make_search_text(
        title="हम उससे बहुत प्यार करते हैं पर फिर भी वो न समझे तो क्या करना चाहिए?",
        understanding={
            "topics": ["प्रेम"],
            "situations": ["एकतरफा प्रेम"],
            "intents": ["क्या करना चाहिए"],
            "concepts": ["आसक्ति"],
            "questions_answered": ["अगर सामने वाला प्रेम न करे तो क्या करें?"],
        },
        temporal={
            "topics": ["संबंध"],
            "situations": ["प्रेम का प्रत्युत्तर न मिलना"],
            "intents": ["मार्गदर्शन"],
            "concepts": ["अपेक्षा"],
        },
        transcript_text="वास्तविक transcript",
    )

    assert value.index("हम उससे") < value.index("वास्तविक transcript")
    assert "एकतरफा प्रेम" in value
    assert "क्या करना चाहिए" in value


def test_intent_query_expansion_is_bounded():
    values = intent_to_queries(
        {
            "situation": "unrequited love",
            "intent": "what should I do",
            "retrieval_phrases": ["एकतरफा प्रेम", "सामने वाला प्रेम न करे"],
            "concepts": ["आसक्ति", "अपेक्षा"],
        },
        "original question",
    )
    assert values[0] == "original question"
    assert len(values) <= 8
    assert "एकतरफा प्रेम" in values
