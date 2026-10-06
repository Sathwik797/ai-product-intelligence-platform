# AI Product Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-D71F00?style=flat&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-V2-E92063?style=flat&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![Google GenAI](https://img.shields.io/badge/Google_GenAI-Gemini_2.5_Flash-4285F4?style=flat&logo=google&logoColor=white)](https://ai.google.dev/)
[![MySQL](https://img.shields.io/badge/MySQL-8.0+-4479A1?style=flat&logo=mysql&logoColor=white)](https://www.mysql.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat)](LICENSE)

A production-oriented, multimodal backend platform engineered to automate e-commerce catalog intelligence. Built with **FastAPI**, **SQLAlchemy ORM**, **Pydantic V2**, and the official **Google GenAI SDK**, the system transforms raw product assets into verified, structured catalog metadata through strict multimodal AI extraction, anti-hallucination guardrails, and a human-in-the-loop review boundary.

---

## 📑 Table of Contents

- [Executive Summary](#-executive-summary)
- [System Architecture](#-system-architecture)
- [Data Layer Architecture](#-data-layer-architecture)
- [Core Capabilities](#-core-capabilities)
- [Technology Stack](#-technology-stack)
- [Project Directory Structure](#-project-directory-structure)
- [API Reference](#-api-reference)
- [Enterprise Reliability & Invariants](#-enterprise-reliability--invariants)
- [Quickstart Guide](#-quickstart-guide)
- [Test Coverage & Verification](#-test-coverage--verification)
- [Product Roadmap](#-product-roadmap)
- [License](#-license)

---

## 🌟 Executive Summary

Modern e-commerce enterprises face significant friction when onboarding raw supplier catalogs. Incomplete product specifications, missing high-intent search keywords, and inconsistent category classifications degrade conversion rates and search rankings.

The **AI Product Intelligence Platform** provides an automated, auditable, and decoupled solution:
- **Multimodal Visual Analysis**: Ingests product images as an ensemble to verify physical attributes, packaging labels, branding, and form factors.
- **Strict Anti-Hallucination Contracts**: Requires structured source citations (`image`, `seller`, `inferred`) and numeric confidence scores for every extracted attribute.
- **Human-in-the-Loop Governance**: Prevents unvetted AI overwrites of transactional data. Sellers can review, modify, or reject generated suggestions with atomic database coordination.
- **Search & RAG Foundation**: Prepares structured metadata for downstream semantic vector indexing (FAISS) and Retrieval-Augmented Generation (RAG).

---

## 🏗️ System Architecture

The application is architected following **Clean Architecture** and **Domain-Driven Design (DDD)** principles, guaranteeing zero leakage of database models or framework dependencies into core AI contracts.

```
                                  CLIENT / FRONTEND / GATEWAY
                                              │
                                              ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                               FASTAPI ROUTING LAYER (app/api/)                             │
│       /categories          /products          /images          /products/{id}/ai/*        │
└─────────────┬───────────────────┬──────────────────┬───────────────────────┬──────────────┘
              │                   │                  │                       │
              ▼                   ▼                  ▼                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                               SERVICE LAYER (app/services/)                               │
│  CategoryService       ProductService        ImageService        AIAcceptanceService      │
│         │                     │                    │                       │              │
│         └─────────────────────┼────────────────────┼───────────────────────┘              │
│                               ▼                    │                                      │
│                     AIGenerationService ───────────┼───────────────────┐                  │
│                               │                    │                   │                  │
└───────────────────────────────┼────────────────────┼───────────────────┼──────────────────┘
                                │                    │                   │
                                ▼                    │                   ▼
                   ┌───────────────────────────┐     │     ┌───────────────────────────┐
                   │  AI PRODUCT CONTEXT       │     │     │  ASYNC BACKGROUND TASKS   │
                   │  BUILDER (app/ai/)        │     │     │  (FastAPI SessionLocal)   │
                   └────────────┬──────────────┘     │     └─────────────┬─────────────┘
                                │                    │                   │
                                ▼                    │                   ▼
                   ┌───────────────────────────┐     │     ┌───────────────────────────┐
                   │  GEMINI PROVIDER BOUNDARY │     │     │  AIGenerationService.     │
                   │  google-genai Client      │     │     │  process_generation()     │
                   └────────────┬──────────────┘     │     └───────────────────────────┘
                                │                    │
                                ▼                    ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                             REPOSITORY LAYER (app/repositories/)                          │
│  CategoryRepository   ProductRepository   ImageRepository  AIGenerationRepo  MetadataRepo │
└─────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                             DATABASE LAYER (SQLAlchemy ORM / MySQL)                       │
│       categories            products            images       product_metadata             │
│                                 └──────────────────┬─────────────────┘                    │
│                                                    ▼                                      │
│                                              ai_generations                               │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🗄️ Data Layer Architecture

The database domain establishes a clear separation between canonical catalog records, active draft pointers, and immutable historical generation ledgers:

```text
1. Canonical Catalog Layer (products)
   └── Contains seller-approved, production data: title, description, brand, sku, price, category_id.

2. Active Draft Pointer Layer (product_metadata)
   └── Singleton 1-to-1 aggregate pointer referencing the currently active AI generation.

3. Immutable Historical Ledger (ai_generations)
   └── Append-only historical log of all AI runs, model versions, latencies, raw outputs, 
       and field-level review states (pending, accepted, modified, rejected).
```

### Entity Relationship Model

```
Category (categories)
   │
   └── 1 : N ── Product (products)
                   │
                   ├── 1 : N (cascade="all, delete-orphan") ── Image (images)
                   │
                   ├── 1 : 1 (uselist=False, cascade="all, delete-orphan") ── ProductMetadata (product_metadata)
                   │                                                              │
                   │                                                              └── N : 1 (active pointer)
                   │                                                                      │
                   └── 1 : N (cascade="all, delete-orphan") ──────────────────────────────▼
                                                                             AIGeneration (ai_generations)
```

---

## ⚡ Core Capabilities

### 1. Catalog & Category Taxonomy Domain
- Hierarchical product classification with unique category naming.
- Transactional product management with unique SKU validation, price constraints, and status tracking.
- Multi-field keyword search across catalog titles, descriptions, and brands.

### 2. Multi-Asset Media Pipeline
- Ensemble product image storage with MIME-type verification, dimension calculation, and display-order sequencing.
- Multi-image aggregation: all uploaded product assets are analyzed concurrently to provide 360-degree context to the vision model.

### 3. Multimodal Vision Intelligence Engine (Gemini 3.1 Flash-Lite by default)
- Powered by the modern `google-genai` SDK (`genai.Client`).
- Multi-image ensemble prompt engineering with zero-shot domain context injection.
- **Anti-Hallucination Contract**: Mandatory structured evidence citations (`image_id`, `seller`, or `inferred`) and bounded confidence scoring `[0.0, 1.0]`.
- Unknown-value explicit nullability: when visual evidence is absent, models return `value = None` with zero confidence rather than hallucinating specifications.

### 4. Human-in-the-Loop Seller Governance
- **Zero Direct Overwrite**: AI drafts are never merged without explicit seller action.
- **One-Click Accept All**: Merges all canonical AI fields into the product catalog in a single atomic transaction.
- **Granular Field Review**: Allows field-by-field acceptance, custom seller modification, rejection, or deferred review.
- **Seller Edit Synchronization**: If a seller manually updates a product field via standard catalog APIs, any active AI generation that previously supplied that field automatically transitions to `modified`.

### 5. Product Embedding Subsystem & Local FAISS Projection
- **Deterministic Text Serialization**: Dedicated `EmbeddingTextBuilder` serializes canonical product attributes and accepted AI metadata in a strict, deterministic section order with normalized whitespace and sorted collections.
- **SHA-256 Invalidation Gate**: Computes SHA-256 digests of canonical documents. If content hash matches stored hash, regeneration is bypassed (`no-op`). Semantic edits mark state `STALE` and trigger async regeneration; non-semantic edits (price, inventory) do NOT trigger regeneration.
- **Concurrency Protection**: Asynchronous background jobs re-read authoritative state and compare SHA-256 hashes to prevent stale jobs from overwriting newer representations.
- **MySQL as System of Record & FAISS Projection**: MySQL is the authoritative system of record (`product_embeddings`). FAISS (`IndexIDMap2` + `IndexFlatIP`) is a rebuildable, disposable vector projection.
- **Atomic Rebuild & Reconciliation**: Self-healing reconciliation restores missing vectors from MySQL, while atomic rebuilds write a new index and swap pointers without corrupting active index state.
- **Explicit Backfill CLI**: `python -m app.commands.backfill_embeddings` allows operator-driven batch generation with fault isolation and change-detection skipping.

---

## 🛠️ Technology Stack

| Domain | Technology | Justification / Purpose |
|---|---|---|
| **Language** | Python 3.11+ | Modern type hinting, async support, high performance. |
| **API Framework** | FastAPI | High-throughput async REST API with automatic OpenAPI validation. |
| **Data Validation** | Pydantic V2 | High-speed C-based validation (`pydantic-core`) with discriminated unions. |
| **Persistence / ORM** | SQLAlchemy 2.0 | Explicit transactions, unit-of-work pattern, declarative mapping. |
| **Database Migrations** | Alembic 1.20+ | Version-controlled, reproducible relational schema migrations. |
| **Database Engine** | MySQL 8.0+ / PyMySQL with SQLite fallback | MySQL is the primary deployment database; SQLite is used as a zero-config local/test fallback. |
| **Vector Engine** | FAISS (`faiss-cpu`) | In-memory dense vector indexing (`IndexIDMap2` + `IndexFlatIP`) with cosine normalization. |
| **AI Models** | Google Gemini 3.1 Flash-Lite / `gemini-embedding-001` | Configurable multimodal visual reasoning and 768-dimensional dense vector embeddings. |
| **AI SDK** | `google-genai` (v2.22.0) | Official modern Google GenAI client library. |
| **Image Processing** | Pillow (PIL) | Automated dimension extraction and image format verification. |
| **Server Engine** | Uvicorn | Production-ready ASGI server implementation. |

---

## 📁 Project Directory Structure

```text
AI-PRODUCT-INTELLIGENCE-PLATFORM/
├── app/
│   ├── ai/                          # AI Boundary & External Integrations
│   │   ├── __init__.py
│   │   ├── context_builder.py       # Domain-to-DTO Context Transformer
│   │   └── gemini_provider.py       # Decoupled Google GenAI SDK Client
│   ├── api/                         # FastAPI Router & Endpoint Controllers
│   │   ├── __init__.py
│   │   ├── ai_generation.py         # AI Generation & Review Endpoints
│   │   ├── category.py              # Category Taxonomy Endpoints
│   │   ├── image.py                 # Product Asset Endpoints
│   │   └── product.py               # Product Catalog Endpoints
│   ├── core/                        # Application Configuration & Settings
│   │   ├── __init__.py
│   │   └── config.py                # Pydantic Settings & Environment Loader
│   ├── db/                          # Database Connections & Session Factory
│   │   ├── __init__.py
│   │   ├── base.py                  # Declarative Base
│   │   ├── database.py              # Engine & SessionLocal
│   │   └── dependencies.py          # FastAPI Session Dependency Injection
│   ├── models/                      # SQLAlchemy Relational Models
│   │   ├── __init__.py
│   │   ├── ai_generation.py         # Historical AI Generation Ledger
│   │   ├── category.py              # Category Taxonomy Table
│   │   ├── image.py                 # Product Images Table
│   │   ├── product.py               # Canonical Product Catalog Table
│   │   └── product_metadata.py      # Active Generation Pointer Table
│   ├── repositories/                # Data Access Layer (Repository Pattern)
│   │   ├── __init__.py
│   │   ├── ai_generation_repository.py
│   │   ├── category_repository.py
│   │   ├── image_repository.py
│   │   ├── product_metadata_repository.py
│   │   └── product_repository.py
│   ├── schemas/                     # Pydantic Data Transfer Objects & Schemas
│   │   ├── __init__.py
│   │   ├── ai_generation.py         # Generation Request/Response Contracts
│   │   ├── ai_metadata.py           # Two-Tier Structured AI Output Schema
│   │   ├── category.py              # Category DTOs
│   │   ├── image.py                 # Image DTOs
│   │   └── product.py               # Product DTOs
│   ├── services/                    # Business Logic & Transaction Orchestration
│   │   ├── __init__.py
│   │   ├── ai_acceptance_service.py # Seller Acceptance & Review Orchestrator
│   │   ├── ai_generation_service.py # AI Generation Lifecycle Orchestrator
│   │   ├── category_service.py
│   │   ├── image_service.py
│   │   └── product_service.py       # Catalog Service with AI Sync Hooks
│   ├── utils/                       # Shared Helpers & Storage Handlers
│   │   ├── __init__.py
│   │   └── file_storage.py          # Asset Upload & Storage Utilities
│   └── main.py                      # Application Entrypoint & Router Assembly
├── docs/
│   └── phases/                      # Detailed Phase Architectural Specifications
│       ├── Phase-01-Project-Setup.md
│       ├── Phase-02-Category-Module.md
│       ├── Phase-03-Product-Module.md
│       ├── Phase-04-Image-Module.md
│       └── Phase-05-AI-Product-Metadata.md
├── scratch/                         # Automated Integration & Regression Test Suites
│   ├── test_ai_acceptance.py        # Step 7 Acceptance & Review Tests
│   ├── test_ai_context_builder.py   # Step 4 Context & Prompt Tests
│   ├── test_ai_generation_api.py    # Step 6 Async API Tests
│   ├── test_ai_generation_service.py# Step 5 Generation Service Tests
│   ├── test_ai_metadata_schema.py   # Step 2 Pydantic Contract Tests
│   └── test_gemini_provider.py      # Step 3 SDK & Boundary Tests
├── requirements.txt                 # Pinned Dependencies
├── README.md                        # Technical Documentation
└── .env                             # Environment Configuration (Git-ignored)
```

---

## 📡 API Reference

### Catalog & Categories
| Method | Endpoint | Description | Status Code |
|---|---|---|---|
| `POST` | `/categories` | Create product category | `201 Created` |
| `GET` | `/categories` | List all taxonomy categories | `200 OK` |
| `POST` | `/products` | Register product in canonical catalog | `201 Created` |
| `GET` | `/products` | List all products with pagination | `200 OK` |
| `GET` | `/products/{id}` | Retrieve product details | `200 OK` |
| `PUT` | `/products/{id}` | Update product (auto-syncs AI review state) | `200 OK` |
| `DELETE`| `/products/{id}` | Delete product and cascade related assets | `204 No Content` |
| `POST` | `/products/{id}/images` | Upload image asset for product | `201 Created` |

### AI Product Intelligence & Governance
| Method | Endpoint | Description | Status Code |
|---|---|---|---|
| `POST` | `/products/{id}/ai/generate` | Trigger asynchronous multimodal metadata generation | `202 Accepted` |
| `GET` | `/products/{id}/ai/generations/{gen_id}` | Query generation execution metrics & raw output | `200 OK` |
| `GET` | `/products/{id}/ai/current` | Retrieve currently active draft and review state | `200 OK` |
| `POST` | `/products/{id}/ai/accept-all` | One-click accept all valid AI fields into catalog | `200 OK` |
| `POST` | `/products/{id}/ai/review` | Granular field review (`accept`, `modify`, `reject`) | `200 OK` |

#### Sample Review Payload (`POST /products/{id}/ai/review`):
```json
{
  "decisions": {
    "title": { "action": "accept" },
    "description": {
      "action": "modify",
      "modified_value": "Overridden seller description with custom warranty details."
    },
    "brand": { "action": "reject" },
    "category": { "action": "accept" },
    "tags": { "action": "accept" },
    "keywords": { "action": "reject" }
  }
}
```

---

## 🔒 Enterprise Reliability & Invariants

1. **ACID Transaction Boundaries**:
   - Updating `Product` fields and `AIGeneration.acceptance_state` executes in the exact same database transaction. A failure in either entity triggers an immediate `db.rollback()`.
2. **Immutable Audit Ledger**:
   - `ai_generations.output` is write-once and strictly immutable. When a seller modifies an AI suggestion, the original AI text is preserved verbatim in `output`, while the seller's override is stored in `Product` and tagged as `"modified"` in `acceptance_state`.
3. **Processing Idempotency**:
   - Background generation tasks enforce strict state machine transitions (`pending` ➔ `processing` ➔ `completed`/`failed`). Duplicate invocations on active or finalized runs return immediately without duplicate LLM calls.
4. **Isolated Worker Sessions**:
   - Background tasks execute in isolated database sessions (`SessionLocal()`) with guaranteed release in `finally` blocks, preventing thread pool connection exhaustion.
5. **Separation of Canonical vs. Discovery Attributes**:
   - The canonical `products` table maintains strict columns (`title`, `description`, `brand`, `category_id`).
   - Discovery attributes (`tags`, `keywords`, `attributes`) are approved into `acceptance_state` for downstream search/indexing, but are strictly excluded from `applied_fields` to prevent phantom database writes.

---

## 🚀 Quickstart Guide

### Prerequisites
- **Python 3.11+**
- **MySQL 8.0+**
- **Google Gemini API Key** ([Google AI Studio](https://aistudio.google.com/))

### 1. Clone Repository & Setup Virtual Environment
```bash
git clone https://github.com/Sathwik797/AI-PRODUCT-INTELLIGENCE-PLATFORM.git
cd AI-PRODUCT-INTELLIGENCE-PLATFORM

python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the project root:
```env
APP_NAME="AI Product Intelligence Platform"
APP_VERSION="1.0.0"
DEBUG=True

# Database Configuration
DATABASE_URL="mysql+pymysql://username:password@localhost:3306/product_intelligence_db"

# Google Gemini API
GEMINI_API_KEY="your-google-gemini-api-key-here"
```

### 4. Database Migrations (Alembic)
Schema management is handled explicitly through **Alembic migrations** (startup `create_all()` has been deprecated to ensure production-safe, auditable schema evolution).

- **For existing populated databases**: Stamp the current Phase 01–05 baseline without re-running DDL:
  ```bash
  alembic stamp head
  ```
- **For fresh databases**: Run all migrations to establish the schema:
  ```bash
  alembic upgrade head
  ```

#### Common Alembic Commands
```bash
# Create a new versioned migration after model changes
alembic revision --autogenerate -m "describe_changes"

# Apply pending migrations
alembic upgrade head

# Roll back the most recent migration (test environments only)
alembic downgrade -1

# Show current migration revision
alembic current

# View full migration revision history
alembic history
```
> [!NOTE]
> All future schema modifications (including Phase 06 embedding tables) must be introduced exclusively through versioned Alembic revisions.

### 5. Run Development Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Access Interactive Documentation
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 🧪 Test Coverage & Verification

The repository documents **121 automated tests** covering the Phase 05 AI-generation and Phase 06 embedding/vector-store suites. The 121-test figure is a repository-reported result; it has not been re-executed as part of this audit.

```bash
# Run Phase 06 Embedding & Vector Store Suites
python scratch/test_embedding_text_builder.py
python scratch/test_embedding_provider.py
python scratch/test_vector_store_faiss.py
python scratch/test_embedding_service.py
python scratch/test_backfill_cli.py
python scratch/test_embedding_migration.py

# Run Complete Phase 05 Regression Test Suite
python scratch/test_ai_metadata_schema.py
python scratch/test_gemini_provider.py
python scratch/test_ai_context_builder.py
python scratch/test_ai_generation_service.py
python scratch/test_ai_generation_api.py
python scratch/test_ai_acceptance.py
```

### Repository-Reported Test Suite Summary
| Suite | Target Layer | Tests | Status |
|---|---|---|---|
| `test_embedding_text_builder.py` | Deterministic ordering, collection normalization, L×W×H dimensions, SHA-256 | 4 | ✅ PASS |
| `test_embedding_provider.py` | Abstract port, Google adapter, mock provider, 768-dim validation, error handling | 3 | ✅ PASS |
| `test_vector_store_faiss.py` | IndexIDMap2, L2 normalization, atomic persistence, atomic rebuild & failure isolation | 3 | ✅ PASS |
| `test_embedding_service.py` | Lifecycle transitions, skip unchanged (Q38), semantic vs price-only change (Q43), hash gate (Q44), reconciliation (Q41) | 5 | ✅ PASS |
| `test_backfill_cli.py` | Explicit CLI, skip unchanged, item fault isolation, retry safety | 1 | ✅ PASS |
| `test_embedding_migration.py` | Alembic upgrade to Phase 06, clean downgrade -1 to baseline | 1 | ✅ PASS |
| `test_ai_metadata_schema.py` | Two-tier Pydantic contracts, evidence, recursive depth limit | 18 | ✅ PASS |
| `test_gemini_provider.py` | Provider configuration, multimodal construction, error mapping | 26 | ✅ PASS |
| `test_ai_context_builder.py` | Domain-to-DTO conversion, prompt rules, image ordering | 16 | ✅ PASS |
| `test_ai_generation_service.py` | Monotonic numbering, lifecycle state machine, rollback safety | 18 | ✅ PASS |
| `test_ai_generation_api.py` | Async BackgroundTasks, SessionLocal isolation, REST routes | 12 | ✅ PASS |
| `test_ai_acceptance.py` | Accept-all, field-level review, seller edit sync, immutability | 14 | ✅ PASS |
| **Total Automated Tests (Phase 05/06)** | | **121** | **Repository-reported 100% PASS** |

---

## 🗺️ Product Roadmap

- [x] **Phase 01 — Project Setup**: Architecture baseline, FastAPI configuration, and settings management.
- [x] **Phase 02 — Category Module**: Relational category taxonomy and validation.
- [x] **Phase 03 — Product Module**: Product catalog domain, SKU uniqueness, and query filters.
- [x] **Phase 04 — Image Module**: Multi-image upload, MIME validation, and disk storage.
- [x] **Phase 05 — AI Product Metadata Generation**:
  - [x] Step 1: Relational database models (`ai_generations`, `product_metadata`).
  - [x] Step 2: Structured Pydantic contracts with visual evidence and confidence bounds.
  - [x] Step 3: Google GenAI SDK integration with isolated `GeminiProvider`.
  - [x] Step 4: Ensemble multimodal context builder and anti-hallucination prompt.
  - [x] Step 5: Atomic generation service with monotonic numbering and rollback safety.
  - [x] Step 6: Asynchronous execution API via FastAPI `BackgroundTasks`.
  - [x] Step 7: Human-in-the-loop review, field acceptance, and seller edit synchronization.
- [x] **Phase 06 — Product Embeddings**:
  - [x] Step 1: `ProductEmbedding` MySQL model and Alembic migration `70f0c7f28370`.
  - [x] Step 2: Deterministic `EmbeddingTextBuilder` & SHA-256 content-hash invalidation.
  - [x] Step 3: Decoupled `EmbeddingProvider` port & `GoogleGeminiEmbeddingProvider` (`gemini-embedding-001` at 768 dimensions).
  - [x] Step 4: `VectorStore` port & `FAISSVectorStore` (`IndexIDMap2` + `IndexFlatIP`) with cosine normalization and atomic rebuild.
  - [x] Step 5: `EmbeddingService` with lifecycle management (`PENDING`, `GENERATING`, `READY`, `STALE`, `FAILED`), content-hash concurrency gate, and reconciliation.
  - [x] Step 6: Invalidation hooks on semantic catalog/AI review changes; price-only neutrality.
  - [x] Step 7: Explicit batch backfill CLI (`python -m app.commands.backfill_embeddings`).
- [x] **Phase 07 — Semantic Search with FAISS**: Hybrid MySQL + FAISS candidate retrieval, eligibility filtering, ranking, and bounded K expansion.
- [x] **Phase 07.2 — Retrieval-Augmented Generation (RAG)**: Grounded product-query endpoint with typed responses.
- [x] **Phase 08 — Product Recommendations**: Hybrid recommendation endpoint with normalized scoring and match reasons.
- [ ] **Phase 09 — Enterprise Deployment & Observability**: Docker/containerization, CI/CD, and production metrics.

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.