"""FastAPI router for AI product metadata generation."""

import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.dependencies import get_db
from app.repositories.ai_generation_repository import AIGenerationRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.image_repository import ImageRepository
from app.repositories.product_metadata_repository import ProductMetadataRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.ai_generation import (
    AIAcceptSelectedRequest,
    AIAcceptanceResponse,
    AIGenerationStatusResponse,
    AIGenerationTriggerResponse,
)
from app.services.ai_acceptance_service import (
    AIAcceptanceService,
    AIAcceptanceServiceError,
    AcceptanceValidationError,
    InvalidGenerationStateError,
    NoActiveGenerationError,
    ProductNotFoundError as AcceptanceProductNotFoundError,
)
from app.services.ai_generation_service import (
    AIGenerationService,
    ProductNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["AI Product Metadata"]
)

# Dependency wiring
product_repository = ProductRepository()
image_repository = ImageRepository()
category_repository = CategoryRepository()
ai_generation_repository = AIGenerationRepository()
product_metadata_repository = ProductMetadataRepository()

ai_generation_service = AIGenerationService(
    product_repository=product_repository,
    image_repository=image_repository,
    category_repository=category_repository,
    ai_generation_repository=ai_generation_repository,
    product_metadata_repository=product_metadata_repository,
)

from app.services.embedding_service import EmbeddingService

embedding_service = EmbeddingService()

ai_acceptance_service = AIAcceptanceService(
    product_repository=product_repository,
    ai_generation_repository=ai_generation_repository,
    product_metadata_repository=product_metadata_repository,
    category_repository=category_repository,
    embedding_service=embedding_service,
)


def process_generation_task(generation_id: int):
    """Background task adapter executing AI generation with a fresh database session.

    FastAPI BackgroundTasks execute outside the request lifecycle. This adapter
    instantiates an isolated database session from SessionLocal() and guarantees
    clean session termination in the finally block.
    """
    db: Session = SessionLocal()
    try:
        ai_generation_service.process_generation(db, generation_id)
    except Exception as exc:
        logger.error("Background AI generation failed for generation %s: %s", generation_id, exc)
    finally:
        db.close()


@router.post(
    "/products/{product_id}/ai/generate",
    response_model=AIGenerationTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED
)
def trigger_ai_generation(
    product_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Initiates an asynchronous multimodal AI metadata generation run for a product."""
    try:
        generation = ai_generation_service.create_pending_generation(db, product_id)
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception:
        logger.exception("Failed to initiate AI generation for product %s", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate AI generation."
        )

    # Schedule background processing with the exact created generation_id
    background_tasks.add_task(process_generation_task, generation.id)

    return AIGenerationTriggerResponse(
        generation_id=generation.id,
        product_id=generation.product_id,
        status=generation.status
    )


@router.get(
    "/products/{product_id}/ai/generations/{generation_id}",
    response_model=AIGenerationStatusResponse,
    status_code=status.HTTP_200_OK
)
def get_ai_generation_status(
    product_id: int,
    generation_id: int,
    db: Session = Depends(get_db)
):
    """Retrieves status, execution metrics, and generated output for a generation run."""
    generation = ai_generation_repository.get_by_id(db, generation_id)
    if not generation or generation.product_id != product_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation not found."
        )

    return AIGenerationStatusResponse(
        generation_id=generation.id,
        product_id=generation.product_id,
        generation_number=generation.generation_number,
        status=generation.status,
        output=generation.output,
        acceptance_state=generation.acceptance_state,
        processing_time=generation.processing_time,
        error_message=generation.error_message,
        started_at=generation.started_at,
        completed_at=generation.completed_at,
        created_at=generation.created_at
    )


@router.get(
    "/products/{product_id}/ai/current",
    response_model=AIGenerationStatusResponse,
    status_code=status.HTTP_200_OK
)
def get_current_ai_generation(
    product_id: int,
    db: Session = Depends(get_db)
):
    """Retrieves the active current AI generation and its acceptance state for a product."""
    try:
        generation = ai_acceptance_service.get_active_generation(db, product_id)
    except (AcceptanceProductNotFoundError, NoActiveGenerationError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except InvalidGenerationStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception:
        logger.exception("Failed to retrieve current generation for product %s", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve current generation."
        )

    return AIGenerationStatusResponse(
        generation_id=generation.id,
        product_id=generation.product_id,
        generation_number=generation.generation_number,
        status=generation.status,
        output=generation.output,
        acceptance_state=generation.acceptance_state,
        processing_time=generation.processing_time,
        error_message=generation.error_message,
        started_at=generation.started_at,
        completed_at=generation.completed_at,
        created_at=generation.created_at
    )


@router.post(
    "/products/{product_id}/ai/accept-all",
    response_model=AIAcceptanceResponse,
    status_code=status.HTTP_200_OK
)
def accept_all_ai_metadata(
    product_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Accepts all valid AI-generated fields for the current active generation in one click."""
    try:
        return ai_acceptance_service.accept_all(db, product_id, background_tasks=background_tasks)
    except (AcceptanceProductNotFoundError, NoActiveGenerationError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except (InvalidGenerationStateError, AcceptanceValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception:
        logger.exception("Failed to accept AI metadata for product %s", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept AI metadata."
        )


@router.post(
    "/products/{product_id}/ai/review",
    response_model=AIAcceptanceResponse,
    status_code=status.HTTP_200_OK
)
def review_ai_metadata(
    product_id: int,
    payload: AIAcceptSelectedRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Applies granular field-level seller review decisions to the current active generation."""
    try:
        return ai_acceptance_service.review_selected(
            db=db,
            product_id=product_id,
            decisions=payload.decisions,
            background_tasks=background_tasks
        )
    except (AcceptanceProductNotFoundError, NoActiveGenerationError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except (InvalidGenerationStateError, AcceptanceValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception:
        logger.exception("Failed to apply AI metadata review for product %s", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to apply AI metadata review."
        )

