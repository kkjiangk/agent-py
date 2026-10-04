from __future__ import annotations

import pytest

from super_ai.retrieval.hybrid import (
    rank_bm25_documents,
    reciprocal_rank_fusion,
    tokenize_hybrid_text,
)


def test_mixed_tokenizer_preserves_operational_terms_and_chinese_bigrams() -> None:
    tokens = tokenize_hybrid_text("API 超时错误 InternalError.Algo.InvalidParameter /v1/chat")

    assert "api" in tokens
    assert "超时" in tokens
    assert "错误" in tokens
    assert "internalerror.algo.invalidparameter" in tokens
    assert "v1/chat" in tokens


def test_bm25_returns_exact_keyword_matches_and_excludes_no_overlap() -> None:
    ranks = rank_bm25_documents(
        query="E_CONN_RESET api-gateway",
        documents=[
            "通用网络故障排查说明",
            "api-gateway failed with E_CONN_RESET and retried",
            "api-worker request succeeded",
        ],
        limit=20,
    )

    assert [rank.index for rank in ranks] == [1]
    assert ranks[0].score > 0


def test_bm25_small_corpus_uses_positive_idf_for_exact_identifier() -> None:
    ranks = rank_bm25_documents(
        query="HYBRID-RRF-74291",
        documents=[
            "故障码 HYBRID-RRF-74291 表示蓝色队列租约过期。",
            "通用服务健康检查说明。",
        ],
    )

    assert [rank.index for rank in ranks] == [0]
    assert ranks[0].score > 0


def test_bm25_high_frequency_terms_never_create_negative_scores() -> None:
    ranks = rank_bm25_documents(
        query="服务 超时",
        documents=[
            "服务发生超时，需要检查连接池。",
            "服务运行正常。",
            "服务健康检查通过。",
        ],
    )

    assert [rank.index for rank in ranks] == [0, 1, 2]
    assert all(rank.score >= 0 for rank in ranks)
    assert ranks[0].score > ranks[1].score


def test_rrf_combines_shared_candidates_with_k_60_and_deterministic_order() -> None:
    fused = reciprocal_rank_fusion(
        vector_keys=["semantic", "shared", "vector-only"],
        bm25_keys=["shared", "exact", "semantic"],
        limit=20,
    )

    assert [item.key for item in fused] == [
        "shared",
        "semantic",
        "exact",
        "vector-only",
    ]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[0].vector_rank == 2
    assert fused[0].bm25_rank == 1


def test_rrf_rejects_invalid_k() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        reciprocal_rank_fusion(vector_keys=[], bm25_keys=[], limit=20, k=0)
