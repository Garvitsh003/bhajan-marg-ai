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
