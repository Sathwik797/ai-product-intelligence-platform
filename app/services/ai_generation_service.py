"""AI Generation Service for AI Product Intelligence Platform.

Phase 05 – Step 5: AI Generation Business & Orchestration Layer.

Orchestrates the end-to-end lifecycle of an AI product metadata generation run:
- Validates product existence in transactional domain.
- Assembles domain context (Product, Images, Categories) via AIProductContextBuilder.
- Maintains strict generation lifecycle state machine: pending -> processing -> completed / failed.
- Enforces monotonically increasing generation numbering across attempts.
- Coordinates successful generation completion and ProductMetadata current pointer
  atomically within the same database transaction.
- Prevents failed generations from updating the active draft pointer.
- Measures elapsed processing duration using a monotonic clock.
- Initializes field-level seller acceptance state.
"""

from datetime import datetime, timezone
import logging
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.ai.context_builder import AIProductContextBuilder
from app.ai.gemini_provider import GeminiProvider
from app.models.ai_generation import AIGeneration
from app.repositories.ai_generation_repository import AIGenerationRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.image_repository import ImageRepository
from app.repositories.product_metadata_repository import ProductMetadataRepository
from app.repositories.product_repository import ProductRepository

# Explicit metadata version constants
PROMPT_VERSION = "v1"
SCHEMA_VERSION = "v1"


# ==============================================================================
# SERVICE EXCEPTIONS (Domain-level, zero FastAPI HTTPException dependency)
# ==============================================================================

class AIGenerationServiceError(Exception):
    """Base exception for all AI generation service errors."""
    pass


class ProductNotFoundError(AIGenerationServiceError, ValueError):
    """Raised when the specified product does not exist in the database."""
    pass


class AIGenerationExecutionError(AIGenerationServiceError):
    """Raised when AI generation execution fails (Gemini API, validation, etc.)."""
    pass


# ==============================================================================
# AI GENERATION SERVICE
# ==============================================================================

class AIGenerationService:
    """Service orchestrating AI product metadata generation lifecycle."""

    def __init__(
        self,
        product_repository: ProductRepository,
        image_repository: ImageRepository,
        category_repository: CategoryRepository,
        ai_generation_repository: AIGenerationRepository,
        product_metadata_repository: ProductMetadataRepository,
        provider: Optional[GeminiProvider] = None,
        context_builder: Optional[AIProductContextBuilder] = None,
    ):
        self.product_repository = product_repository
        self.image_repository = image_repository
        self.category_repository = category_repository
        self.ai_generation_repository = ai_generation_repository
        self.product_metadata_repository = product_metadata_repository
        self.provider = provider or GeminiProvider()
        self.context_builder = context_builder or AIProductContextBuilder()

    def create_pending_generation(
        self,
        db: Session,
        product_id: int
    ) -> AIGeneration:
        """Validates product existence and creates an initial 'pending' AIGeneration record.

        Args:
            db: Active SQLAlchemy database session.
            product_id: Primary key of the product.

        Returns:
            Newly created AIGeneration record with status='pending'.

        Raises:
            ProductNotFoundError: If the product does not exist in the database.
        """
        # 1. Validate product exists
        product = self.product_repository.get_by_id(db, product_id)
        if not product:
            raise ProductNotFoundError(f"Product with id {product_id} not found.")

        # 2. Determine monotonically increasing generation number
        generation_number = self.ai_generation_repository.get_next_generation_number(
            db=db,
            product_id=product_id
        )

        # 3. Create initial generation record with status='pending'
        model_name = getattr(self.provider.config, "model_name", "gemini-3.1-flash-lite")
        generation = AIGeneration(
            product_id=product_id,
            generation_number=generation_number,
            status="pending",
            model_name=model_name,
            model_version=None,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
        )
        return self.ai_generation_repository.create(db, generation, commit=True)

    def process_generation(
        self,
        db: Session,
        generation_id: int
    ) -> AIGeneration:
        """Processes an existing generation through the multimodal AI pipeline.

        Enforces strict processing idempotency:
        - If generation is already completed, failed, or processing, returns immediately
          without invoking the provider or duplicating work.
        - Only 'pending' generations transition to 'processing'.

        Args:
            db: Active SQLAlchemy database session.
            generation_id: Primary key of the AIGeneration record.

        Returns:
            Updated AIGeneration record.

        Raises:
            AIGenerationServiceError: If generation record does not exist.
            AIGenerationExecutionError: If generation inference or validation fails.
        """
        generation = self.ai_generation_repository.get_by_id(db, generation_id)
        if not generation:
            raise AIGenerationServiceError(f"AIGeneration with id {generation_id} not found.")

        # Processing Idempotency: avoid duplicate processing if already claimed or finished
        if generation.status in ("completed", "failed", "processing"):
            return generation

        # Transition state: pending -> processing
        generation.status = "processing"
        generation.started_at = datetime.now(timezone.utc)
        self.ai_generation_repository.update(db, generation, commit=True)

        start_time = time.monotonic()
        try:
            product = self.product_repository.get_by_id(db, generation.product_id)
            if not product:
                raise ProductNotFoundError(f"Product with id {generation.product_id} not found.")

            images = self.image_repository.get_by_product(db, generation.product_id)
            categories = self.category_repository.get_all(db)

            # Assemble decoupled DTO context
            ai_context = self.context_builder.build_context(
                product=product,
                images=images,
                available_categories=categories,
            )

            # Invoke provider boundary
            ai_metadata = self.provider.generate_product_metadata(ai_context)

            # Serialize output to pure JSON dictionary
            output_dict = ai_metadata.model_dump(mode="json")

            # Initialize field-level seller acceptance state for all top-level fields
            acceptance_state = {key: "pending" for key in output_dict.keys()}

            # Record elapsed execution duration
            processing_time = round(time.monotonic() - start_time, 3)

            # Update generation entity attributes
            generation.status = "completed"
            generation.completed_at = datetime.now(timezone.utc)
            generation.processing_time = processing_time
            generation.output = output_dict
            generation.acceptance_state = acceptance_state
            generation.error_message = None

            # Final Success Transaction Coordination:
            # Atomically commit the completed generation and the current_generation_id pointer
            # in the same database transaction so states never diverge.
            self.ai_generation_repository.update(db, generation, commit=False)
            self.product_metadata_repository.set_current_generation(
                db=db,
                product_id=generation.product_id,
                generation_id=generation.id,
                commit=False
            )
            db.commit()
            db.refresh(generation)

            return generation

        except Exception as exc:
            # Failure Path: Record failure state, elapsed time, and error message.
            processing_time = round(time.monotonic() - start_time, 3)

            # Failure-safety rollback: clear any uncommitted or aborted transaction state
            # on the database session before persisting the failure status.
            try:
                db.rollback()
            except Exception as rb_exc:
                logger.error("Session rollback failed for generation %s: %s", generation.id, rb_exc)

            generation.status = "failed"
            generation.completed_at = datetime.now(timezone.utc)
            generation.processing_time = processing_time
            generation.error_message = "AI generation failed. See server logs for diagnostic details."
            logger.error("AI generation failed for generation %s: %s", generation.id, exc, exc_info=True)

            # Persist failure status; DO NOT update ProductMetadata.current_generation_id
            try:
                self.ai_generation_repository.update(db, generation, commit=True)
            except Exception as db_exc:
                logger.critical(
                    "Failed to record failure status for generation %s: %s",
                    generation.id,
                    db_exc
                )

            raise AIGenerationExecutionError(
                f"AI product metadata generation failed for product {generation.product_id}: {exc}"
            ) from exc

    def generate(
        self,
        db: Session,
        product_id: int
    ) -> AIGeneration:
        """Executes a complete AI product metadata generation run synchronously.

        Delegates cleanly to create_pending_generation() and process_generation().
        """
        pending_generation = self.create_pending_generation(db, product_id)
        return self.process_generation(db, pending_generation.id)
