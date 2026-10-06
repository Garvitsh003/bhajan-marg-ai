from app import llm, retrieval


def test_expand_roman_hindi_query_to_devanagari(monkeypatch):
    def fake_chat(messages, **kwargs):
        return (
            '{"queries":['
            '"radha ashtmi vrat",'
            '"radha ashtami vrat",'
            '"राधा अष्टमी व्रत",'
            '"Radha Ashtami fast"'
            ']}'
        )

    monkeypatch.setattr(llm, "ollama_chat", fake_chat)

    queries = llm.expand_retrieval_queries("radha ashtmi vrat")

    assert queries[0] == "radha ashtmi vrat"
    assert "radha ashtami vrat" in queries
    assert "राधा अष्टमी व्रत" in queries


def test_retrieve_searches_all_variants_and_reranks_original(monkeypatch):
    queries = [
        "radha ashtmi vrat",
        "radha ashtami vrat",
        "राधा अष्टमी व्रत",
    ]

    monkeypatch.setattr(
        retrieval,
        "understand_query",
        lambda question: {
            "language": "en",
            "domain": "spiritual practice",
            "situation": "",
            "intent": "",
            "entities": [],
            "emotions": [],
            "constraints": [],
            "concepts": [],
            "retrieval_phrases": [],
        },
    )

    monkeypatch.setattr(
        retrieval,
        "expand_retrieval_queries",
        lambda question: queries,
    )

    searched = []

    def fake_search(query):
        searched.append(query)
        if query == "राधा अष्टमी व्रत":
            return [{
                "point_id": "p-hindi",
                "video_id": "vid-hindi",
                "title": "राधा अष्टमी व्रत",
                "chunk_index": 0,
                "start_ms": 4000,
                "end_ms": 61000,
                "text": "राधा अष्टमी व्रत का वास्तविक अर्थ...",
                "fusion_score": 0.8,
            }]
        return [{
            "point_id": "p-noise",
            "video_id": "vid-noise",
            "title": "अन्य सत्संग",
            "chunk_index": 0,
            "start_ms": 0,
            "end_ms": 30000,
            "text": "सामान्य भक्ति चर्चा",
            "fusion_score": 0.4,
        }]

    monkeypatch.setattr(retrieval, "hybrid_search", fake_search)

    rerank_queries = []

    def fake_rerank(query, candidates, top_k):
        rerank_queries.append(query)
        ranked = []
        for item in candidates:
            ranked.append({
                **item,
                "rerank_score": 0.99 if item["video_id"] == "vid-hindi" else 0.25,
            })
        return sorted(ranked, key=lambda x: x["rerank_score"], reverse=True)[:top_k]

    monkeypatch.setattr(retrieval, "rerank", fake_rerank)
    monkeypatch.setattr(
        retrieval,
        "judge_evidence",
        lambda question, sources, algorithmic_level: {
            "level": "direct",
            "source_indices": [0],
            "reason": "Exact Radha Ashtami teaching found",
        },
    )

    result = retrieval.retrieve("radha ashtmi vrat")

    assert searched == queries
    assert rerank_queries == ["radha ashtmi vrat"]
    assert result["search_queries"] == queries
    assert result["level"] == "direct"
    assert result["sources"][0]["video_id"] == "vid-hindi"


def test_intent_aware_retrieval_merges_semantic_queries(monkeypatch):
    monkeypatch.setattr(
        retrieval,
        "understand_query",
        lambda question: {
            "language": "hinglish",
            "domain": "relationship",
            "situation": "unrequited love",
            "intent": "what should I do",
            "entities": [],
            "emotions": ["hurt"],
            "constraints": ["not reciprocated"],
            "concepts": ["एकतरफा प्रेम"],
            "retrieval_phrases": ["सामने वाला प्रेम न करे तो क्या करें?"],
        },
    )
    monkeypatch.setattr(
        retrieval,
        "expand_retrieval_queries",
        lambda question: [question, "जिससे प्रेम हो वह प्रेम न करे"],
    )

    searched = []

    def fake_search(query, limit=None):
        searched.append(query)
        return [{
            "point_id": "target",
            "video_id": "5vzzUFSo_E4",
            "title": "हम उससे बहुत प्यार करते हैं पर फिर भी वो न समझे तो क्या करना चाहिए?",
            "chunk_index": 3,
            "start_ms": 120000,
            "end_ms": 180000,
            "text": "प्रेम के विषय में वास्तविक transcript evidence।",
            "search_text": "title semantic situation intent",
            "semantic": {"situations": ["एकतरफा प्रेम"]},
            "fusion_score": 0.9,
        }]

    monkeypatch.setattr(retrieval, "hybrid_search", fake_search)
    monkeypatch.setattr(
        retrieval,
        "rerank",
        lambda question, candidates, top_k: [
            {**candidates[0], "rerank_score": 0.97}
        ],
    )
    monkeypatch.setattr(
        retrieval,
        "judge_evidence",
        lambda question, sources, algorithmic_level: {
            "level": "direct",
            "source_indices": [0],
            "reason": "Direct semantic match",
        },
    )

    result = retrieval.retrieve(
        "mei ek ladki se bohot pyaar krta hu pr voh merse pyaar nhi karti, mujhe kya krna chahiye?"
    )

    assert result["level"] == "direct"
    assert result["sources"][0]["video_id"] == "5vzzUFSo_E4"
    assert result["query_intent"]["situation"] == "unrequited love"
    assert "सामने वाला प्रेम न करे तो क्या करें?" in result["search_queries"]
