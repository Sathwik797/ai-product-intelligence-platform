"""RAG Orchestration Service.

Implements Q74, Q77, Q86:
- Orchestrates: Retrieval -> Zero-Result Guard -> Prompt -> LLM -> Validation -> 1 Retry -> Fail-Closed Fallback.
- Zero-results: zero Gemini calls, deterministic query relaxation suggestions.
- Attempt 1 validation failure: retries once with deterministic feedback over identical bundle.
- Attempt 2 validation failure: fails closed, suppresses unverified model answer, returns safe fallback.
- Collects minimal practical execution telemetry.
"""

import logging
import time
from typing import Any, Optional
from sqlalchemy.orm import Session

from app.ai.rag_gemini_provider import GoogleGeminiRAGProvider
from app.rag.citation_validator import CitationValidator, ValidationResult
from app.rag.knowledge import RAGRetrievalService
from app.rag.llm_provider import RAGLLMProvider, RAGProviderError
from app.rag.prompt_builder import RAGPromptBuilder
from app.schemas.rag import (
    RAGClaim,
    RAGConfig,
    RAGModelResponse,
    RAGResponse,
    RAGTelemetry,
)
from app.schemas.search import SearchFilters

logger = logging.getLogger(__name__)


class RAGService:
    """End-to-end orchestrator for Grounded RAG query answering."""

    SAFE_FALLBACK_ANSWER: str = (
        "I found matching products in the catalog, but could not verify all specific product details with "
        "high confidence. Please see the retrieved products below or inspect the product listings directly."
    )

    def __init__(
        self,
        retrieval_service: Optional[RAGRetrievalService] = None,
        prompt_builder: Optional[RAGPromptBuilder] = None,
        llm_provider: Optional[RAGLLMProvider] = None,
        validator: Optional[CitationValidator] = None,
        config: Optional[RAGConfig] = None
    ):
        self.config = config or RAGConfig()
        self.retrieval_service = retrieval_service or RAGRetrievalService(config=self.config)
        self.prompt_builder = prompt_builder or RAGPromptBuilder()
        self.llm_provider = llm_provider or GoogleGeminiRAGProvider(config=self.config)
        self.validator = validator or CitationValidator()

    def answer_query(
        self,
        db: Session,
        query: str
    ) -> RAGResponse:
        """Processes a natural-language question end-to-end with grounded citation guarantees."""
        start_total = time.perf_counter()

        # 1. Retrieval & Context Hydration
        start_retrieval = time.perf_counter()
        bundle, search_response = self.retrieval_service.retrieve_and_hydrate(
            db=db,
            question=query,
            limit=self.config.max_context_products
        )
        retrieval_latency_ms = round((time.perf_counter() - start_retrieval) * 1000.0, 2)

        # 2. Zero-Results Short Circuit (Q77)
        if not bundle.products:
            total_latency_ms = round((time.perf_counter() - start_total) * 1000.0, 2)
            no_results_answer = self._generate_no_results_answer(search_response.metadata.parsed_filters)

            telemetry = RAGTelemetry(
                total_latency_ms=total_latency_ms,
                retrieval_latency_ms=retrieval_latency_ms,
                llm_latency_ms=0.0,
                validation_latency_ms=0.0,
                retry_count=0,
                fallback_triggered=False,
                prompt_version=self.prompt_builder.PROMPT_VERSION,
                model_name=self.config.model_name,
                context_product_count=0,
                input_tokens=None,
                output_tokens=None,
            )

            return RAGResponse(
                query=query,
                answer=no_results_answer,
                claims=[],
                retrieved_products=[],
                telemetry=telemetry,
                status="no_results",
                fallback_reason="No matching catalog products were retrieved."
            )

        # Build retrieved product summary cards for caller visibility
        retrieved_summaries: list[dict[str, Any]] = [
            {
                "product_id": p.product_id,
                "title": p.product_facts.get("title"),
                "price": p.live_catalog_state.get("price"),
                "status": p.live_catalog_state.get("status"),
                "brand": p.product_facts.get("brand"),
                "category": p.product_facts.get("category"),
                "match_reasons": p.search_match_context,
            }
            for p in bundle.products
        ]

        total_llm_latency_ms: float = 0.0
        total_validation_latency_ms: float = 0.0
        retry_count: int = 0
        fallback_triggered: bool = False
        fallback_reason: Optional[str] = None
        final_answer: str = ""
        final_claims: list[RAGClaim] = []
        last_input_tokens: Optional[int] = None
        last_output_tokens: Optional[int] = None
        actual_model_name: str = self.config.model_name

        # 3. Attempt 1: Generation & Validation
        attempt1_success = False
        val_result1: Optional[ValidationResult] = None

        try:
            payload1 = self.prompt_builder.build(bundle=bundle)
            start_llm1 = time.perf_counter()
            resp1, meta1 = self.llm_provider.generate(payload1)
            took_llm1 = round((time.perf_counter() - start_llm1) * 1000.0, 2)
            total_llm_latency_ms += took_llm1
            last_input_tokens = meta1.get("input_tokens")
            last_output_tokens = meta1.get("output_tokens")
            actual_model_name = meta1.get("model_name", actual_model_name)

            start_val1 = time.perf_counter()
            val_result1 = self.validator.validate(resp1, bundle)
            took_val1 = round((time.perf_counter() - start_val1) * 1000.0, 2)
            total_validation_latency_ms += took_val1

            if val_result1.is_valid:
                final_answer = resp1.answer
                final_claims = resp1.claims
                attempt1_success = True
        except RAGProviderError as pe:
            logger.warning(f"RAG LLM provider error on Attempt 1: {pe}")
            val_result1 = ValidationResult(is_valid=False, errors=[str(pe)], feedback_text=str(pe))

        # 4. Attempt 2: Retry with deterministic feedback (Q74)
        if not attempt1_success:
            retry_count = 1
            feedback_text = val_result1.feedback_text if val_result1 else "Invalid schema or claims."
            attempt2_success = False

            try:
                payload2 = self.prompt_builder.build(bundle=bundle, retry_feedback=feedback_text)
                start_llm2 = time.perf_counter()
                resp2, meta2 = self.llm_provider.generate(payload2)
                took_llm2 = round((time.perf_counter() - start_llm2) * 1000.0, 2)
                total_llm_latency_ms += took_llm2
                if meta2.get("input_tokens") is not None:
                    last_input_tokens = meta2.get("input_tokens")
                if meta2.get("output_tokens") is not None:
                    last_output_tokens = meta2.get("output_tokens")
                actual_model_name = meta2.get("model_name", actual_model_name)

                start_val2 = time.perf_counter()
                val_result2 = self.validator.validate(resp2, bundle)
                took_val2 = round((time.perf_counter() - start_val2) * 1000.0, 2)
                total_validation_latency_ms += took_val2

                if val_result2.is_valid:
                    final_answer = resp2.answer
                    final_claims = resp2.claims
                    attempt2_success = True
                else:
                    fallback_reason = "Model output failed verification after retry."
            except RAGProviderError as pe2:
                logger.warning(f"RAG LLM provider error on Attempt 2 retry: {pe2}")
                fallback_reason = "RAG provider failed during retry."

            # 5. Fail Closed Fallback (Q74)
            if not attempt2_success:
                fallback_triggered = True
                final_answer = self.SAFE_FALLBACK_ANSWER
                final_claims = []
                if not fallback_reason:
                    fallback_reason = "Model generated claims failed verification after retry."

        total_latency_ms = round((time.perf_counter() - start_total) * 1000.0, 2)

        telemetry = RAGTelemetry(
            total_latency_ms=total_latency_ms,
            retrieval_latency_ms=retrieval_latency_ms,
            llm_latency_ms=total_llm_latency_ms,
            validation_latency_ms=total_validation_latency_ms,
            retry_count=retry_count,
            fallback_triggered=fallback_triggered,
            prompt_version=self.prompt_builder.PROMPT_VERSION,
            model_name=actual_model_name,
            context_product_count=len(bundle.products),
            input_tokens=last_input_tokens,
            output_tokens=last_output_tokens,
        )

        status_value = "fallback" if fallback_triggered else "success"
        return RAGResponse(
            query=query,
            answer=final_answer,
            claims=final_claims,
            retrieved_products=retrieved_summaries,
            telemetry=telemetry,
            status=status_value,
            fallback_reason=fallback_reason
        )

    def _generate_no_results_answer(self, filters: SearchFilters) -> str:
        """Generates deterministic relaxation guidance when zero products match."""
        suggestions: list[str] = []
        if filters.brand:
            suggestions.append(f"removing the brand filter ('{filters.brand}')")
        if filters.max_price is not None:
            suggestions.append(f"increasing the maximum price limit (₹{filters.max_price})")
        if filters.min_price is not None:
            suggestions.append(f"lowering the minimum price (₹{filters.min_price})")
        if filters.color:
            suggestions.append(f"removing the color filter ('{filters.color}')")
        if filters.size:
            suggestions.append(f"removing the size filter ('{filters.size}')")
        if filters.category:
            suggestions.append(f"broadening the category ('{filters.category}')")

        if suggestions:
            joined = " or ".join(suggestions)
            return (
                f"No products matched your search with the specified constraints. "
                f"You could try {joined}, or use broader search terms."
            )
        return (
            "No products matched your search query in the catalog. "
            "Please try searching with different keywords or broader terms."
        )
