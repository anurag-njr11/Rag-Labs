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
            reasoning["parse"] = "Document has structure (headings/tables). PyMuPDF4LLM preserves Markdown."
        elif ocr_needed:
            parser_type = "pymupdf_text"
            reasoning["parse"] = "Document appears to be scanned. Using PyMuPDF with OCR enabled."
        else:
            parser_type = "pymupdf_text"
            reasoning["parse"] = "Using PyMuPDF for fast plain-text extraction."

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
            reasoning["chunk"] = "Document has structure (headings) or code. Respecting boundaries ensures context."
        elif avg_code > 0.1:
            chunk_type = "recursive"
            reasoning["chunk"] = "Code-heavy document. Recursive chunking respects sentence boundaries in comments."
        else:
            chunk_type = "recursive"
            reasoning["chunk"] = "Using recursive chunking for sentence-aware boundaries."

        # Chunk size: smaller for technical, larger for general
        if avg_code > 0.2:
            chunk_size = 512
            reasoning["chunk"] += " Smaller chunks (512) for code precision."
        elif total_chars > 10_000_000:
            chunk_size = 1024
            reasoning["chunk"] += " Larger chunks (1024) for large corpus."
        elif total_chars < 1_000_000:
            chunk_size = 512
            reasoning["chunk"] += " Smaller chunks (512) for detailed Q&A."
        else:
            chunk_size = 768
            reasoning["chunk"] += " Balanced chunk size (768)."

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
            reasoning["embed"] = f"Non-English detected ({primary_lang}). Using Gemini API for better multilingual support."
        elif has_code and avg_code > 0.15:
            embed_type = "fastembed"
            embed_model = "mixedbread-ai/mxbai-embed-large-v1"
            reasoning["embed"] = "Code-heavy corpus. MXBai (1024d) ranks #1 on MTEB for code retrieval."
        elif estimated_chunks > 50_000:
            embed_type = "fastembed"
            embed_model = "BAAI/bge-base-en-v1.5"
            reasoning["embed"] = "Large corpus (>50k chunks). BGE-base (768d) balances quality and speed."
        elif total_chars < 500_000:
            embed_type = "fastembed"
            embed_model = "BAAI/bge-small-en-v1.5"
            reasoning["embed"] = "Small corpus. BGE-small (384d) is fast and sufficient."
        else:
            embed_type = "fastembed"
            embed_model = "BAAI/bge-base-en-v1.5"
            reasoning["embed"] = "BGE-base (768d) is recommended for general use."

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
            reasoning["vector_store"] = "Small corpus (<1k chunks). NumPy provides exact search."
        elif estimated_chunks < 50_000:
            store_type = "faiss"
            store_config_type = "Flat"
            reasoning["vector_store"] = "Medium corpus (1k–50k chunks). FAISS Flat provides exact, indexed search."
        else:
            store_type = "faiss"
            store_config_type = "HNSW"
            reasoning["vector_store"] = "Large corpus (>50k chunks). FAISS HNSW balances accuracy and speed."

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
            retrieve_reason = "Technical/code corpus. Fused retrieval (dense + keyword + exact) catches symbol matches."
        else:
            retrieve_type = "hybrid"
            retrieve_reason = "Using hybrid retrieval (dense + keyword) for general knowledge."

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
            retrieve_reason += " Pinning section headings that match queries."

        reasoning["retrieve"] = retrieve_reason

        # --- RERANK ---
        if estimated_chunks > 50_000:
            rerank_type = "cross_encoder"
            reasoning["rerank"] = "Large corpus (>50k chunks). Reranking filters noise in dense retrieval."
        else:
            rerank_type = "none"
            reasoning["rerank"] = "Skipping reranking; retrieval quality sufficient without extra cost."

        rerank_config = {"type": rerank_type}

        # --- PROMPT ---
        prompt_config = {
            "type": "cited_qa",
            "max_context_tokens": 4000,
            "say_dont_know": True,
            "source_labels": True,
        }
        reasoning["prompt"] = "Using cited Q&A with max 4000 context tokens and instruction to refuse unanswerable questions."

        # --- GENERATE ---
        if has_code:
            gen_temp = 0.1
            gen_reasoning = "none"
            reasoning["generate"] = "Code-heavy corpus. Temperature=0.1 for precise answers; no extended reasoning."
        else:
            gen_temp = 0.2
            gen_reasoning = "low"
            reasoning["generate"] = "Temperature=0.2 balances quality and diversity. Low reasoning for speed."

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
