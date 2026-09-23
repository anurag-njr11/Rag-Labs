"""Smart recommendation engine: map document characteristics to optimal pipeline config.

Based on corpus metadata (size, code density, structure, domain, etc.),
recommend optimal settings for each pipeline stage.
"""

from __future__ import annotations

from typing import Any

from .pipeline import PipelineConfig


class Recommender:
    """Recommend optimal pipeline configuration based on corpus metadata."""

    @staticmethod
    def recommend(corpus_metadata: dict[str, Any]) -> tuple[PipelineConfig, dict[str, str]]:
        """
        Recommend a pipeline configuration based on corpus characteristics.

        Args:
            corpus_metadata: Aggregated metadata from document_analyzer.aggregate_corpus_metadata()

        Returns:
            (config, reasoning) where:
            - config: Complete PipelineConfig ready to use
            - reasoning: Dict[stage_name] -> explanation of the choice
        """
        reasoning = {}

        # Extract metrics for easier access
        total_chars = corpus_metadata.get("total_char_count", 0)
        avg_code = corpus_metadata.get("avg_code_density", 0.0)
        avg_structure = corpus_metadata.get("avg_structure_density", 0.0)
        has_code = corpus_metadata.get("has_code", False)
        estimated_chunks = corpus_metadata.get("estimated_chunks", 100)
        languages = corpus_metadata.get("languages", ["en"])
        inferred_domains = corpus_metadata.get("inferred_domains", [])
        ocr_needed = corpus_metadata.get("ocr_needed", False)

        # --- PARSER ---
        if avg_structure > 0.2:
            parser_type = "pymupdf4llm"
            reasoning["parse"] = "PyMuPDF4LLM preserves document structure (headings, tables) as Markdown. Recommended when structure matters."
        elif ocr_needed:
            parser_type = "pymupdf_text"
            reasoning["parse"] = "Document appears to be scanned (low char density). Using PyMuPDF with OCR to extract text from images."
        else:
            parser_type = "pymupdf_text"
            reasoning["parse"] = "PyMuPDF extracts text efficiently. Works well for most PDFs and is fast."

        parse_config = {
            "type": parser_type,
            "strip_headers_footers": True,
        }
        if parser_type == "pymupdf_text":
            parse_config["extract_tables"] = True
            parse_config["ocr"] = ocr_needed

        # --- CHUNK ---
        if avg_structure > 0.2 or has_code:
            chunk_type = "structure_aware"
            chunk_size = 512 if has_code else 768
            reasoning["chunk"] = f"Structure-aware chunking respects heading boundaries and keeps code blocks intact. {chunk_size} chars balances context with specificity."
        else:
            chunk_type = "recursive"
            # Chunk size based on corpus size
            if total_chars < 1_000_000:
                chunk_size = 512
                reasoning["chunk"] = "Small corpus (< 1MB). Using 512-char chunks for detailed Q&A. Recursive chunking respects sentence boundaries."
            elif total_chars > 10_000_000:
                chunk_size = 1024
                reasoning["chunk"] = "Large corpus (> 10MB). Using 1024-char chunks to reduce overhead while maintaining context."
            else:
                chunk_size = 768
                reasoning["chunk"] = "Medium corpus. Using 768-char chunks—balanced between specificity and context coverage. Recursive chunking respects sentence breaks."

        chunk_config = {
            "type": chunk_type,
            "size": chunk_size,
            "overlap": 100,
            "unit": "chars",
        }
        if chunk_type == "structure_aware":
            chunk_config["heading_depth"] = 3
            chunk_config["include_heading_in_text"] = True
            chunk_config["min_chunk_size"] = 50

        # --- EMBED ---
        primary_lang = languages[0] if languages else "en"
        if primary_lang != "en":
            embed_type = "api"
            embed_provider = "gemini"
            embed_model = ""  # default
            reasoning["embed"] = f"Non-English detected ({primary_lang}). Gemini API handles multilingual content better than local models."
        elif has_code and avg_code > 0.15:
            embed_type = "fastembed"
            embed_model = "mixedbread-ai/mxbai-embed-large-v1"
            reasoning["embed"] = "Code-heavy corpus (>15% code). MXBai (1024d) ranks #1 on MTEB for code retrieval. Better at matching error messages and symbols."
        elif estimated_chunks > 50_000:
            embed_type = "fastembed"
            embed_model = "BAAI/bge-base-en-v1.5"
            reasoning["embed"] = f"Large corpus ({estimated_chunks:,} chunks). BGE-base (768d) balances quality (MTEB #4) with speed. 210MB download, runs locally."
        elif total_chars < 500_000:
            embed_type = "fastembed"
            embed_model = "BAAI/bge-small-en-v1.5"
            reasoning["embed"] = "Small corpus. BGE-small (384d) is fast, lightweight (67MB), and sufficient for precise retrieval."
        else:
            embed_type = "fastembed"
            embed_model = "BAAI/bge-base-en-v1.5"
            reasoning["embed"] = "BGE-base (768d) is the balanced recommendation—ranked #4 on MTEB, handles both semantic and exact matches well."

        embed_config = {
            "type": embed_type,
            "normalize": True,
        }
        if embed_type == "fastembed":
            embed_config["model"] = embed_model
            embed_config["batch_size"] = 32
        else:
            embed_config["provider"] = embed_provider
            embed_config["model"] = embed_model
            embed_config["batch_size"] = 50

        # --- VECTOR STORE ---
        if estimated_chunks < 1000:
            store_type = "numpy"
            reasoning["vector_store"] = f"Tiny corpus ({estimated_chunks} chunks). NumPy provides exact, deterministic search with no approximation."
        elif estimated_chunks < 50_000:
            store_type = "faiss"
            store_config_type = "Flat"
            reasoning["vector_store"] = f"Medium corpus ({estimated_chunks:,} chunks). FAISS Flat is exact (no approximation), indexed, and deterministic. Every search gets the same results."
        else:
            store_type = "faiss"
            store_config_type = "HNSW"
            reasoning["vector_store"] = f"Large corpus ({estimated_chunks:,} chunks). FAISS HNSW uses graph-based search—fast (~5ms queries) and approximate (97%+ recall). Trade-off: slightly different results on re-index."

        vector_store_config: dict[str, Any] = {
            "type": store_type,
            "metric": "cosine",
        }
        if store_type == "faiss":
            vector_store_config["index_type"] = store_config_type
            if store_config_type == "IVFFlat":
                vector_store_config["nlist"] = 64
                vector_store_config["nprobe"] = 8
            elif store_config_type == "HNSW":
                vector_store_config["hnsw_m"] = 32
                vector_store_config["ef_construction"] = 200
                vector_store_config["ef_search"] = 64

        # --- RETRIEVE ---
        if has_code or "technical" in inferred_domains:
            retrieve_type = "fused"
            retrieve_reason = "Technical/code corpus detected. Fused retrieval (dense + keyword + exact) catches error messages, symbol names, and API references. Exact-match weight boosted to 1.5."
        else:
            retrieve_type = "hybrid"
            retrieve_reason = "Hybrid retrieval (dense semantic + keyword BM25) works well for general knowledge. Returns top 8 results via RRF fusion."

        retrieve_config = {
            "type": retrieve_type,
            "top_k": 8,
            "fusion": "rrf",
            "rrf_k": 60,
            "dense_weight": 1.0,
            "keyword_weight": 1.0,
            "exact_weight": 1.5,
            "candidates": 40,
            "min_score": 0.0,
            "pin_definitions": has_code,
            "mmr": False,
            "mmr_lambda": 0.7,
        }
        if estimated_chunks > 10_000 and has_code:
            retrieve_config["pin_definitions"] = True
            retrieve_reason += " Section headings that match query terms are pinned to top-5 (helps for finding API docs)."

        reasoning["retrieve"] = retrieve_reason

        # --- RERANK ---
        if estimated_chunks > 50_000:
            rerank_type = "cross_encoder"
            reasoning["rerank"] = f"Large corpus ({estimated_chunks:,} chunks). Cross-encoder reranking uses a second model to filter noise. Adds ~50ms per query but improves accuracy."
        else:
            rerank_type = "none"
            reasoning["rerank"] = "Corpus size is moderate. Retrieval + fusion quality sufficient without reranking overhead."

        rerank_config = {"type": rerank_type}

        # --- PROMPT ---
        prompt_config = {
            "type": "cited_qa",
            "max_context_tokens": 4000,
            "say_dont_know": True,
            "source_labels": True,
        }
        reasoning["prompt"] = "Cited Q&A template: LLM cites chunks with [1], [2] markers. Max 4000 tokens keeps context tight. 'Say don't know' prevents hallucination on unanswerable questions."

        # --- GENERATE ---
        if has_code:
            gen_temp = 0.1
            gen_reasoning = "none"
            reasoning["generate"] = "Code corpus: temperature=0.1 makes answers reproducible (deterministic). No extended reasoning (faster, focused on accuracy)."
        else:
            gen_temp = 0.2
            gen_reasoning = "low"
            reasoning["generate"] = "Temperature=0.2 balances focus + diversity. Low reasoning effort (~0.5x overhead) for speed. Gemini default model."

        generate_config = {
            "type": "gemini",
            "model": "",  # empty = use provider default
            "temperature": gen_temp,
            "top_p": 1.0,
            "max_tokens": 2048,
            "reasoning_effort": gen_reasoning,
        }

        # --- BUILD FULL CONFIG ---
        config: PipelineConfig = {
            "parse": parse_config,
            "chunk": chunk_config,
            "embed": embed_config,
            "vector_store": vector_store_config,
            "retrieve": retrieve_config,
            "rerank": rerank_config,
            "prompt": prompt_config,
            "generate": generate_config,
        }

        return config, reasoning
