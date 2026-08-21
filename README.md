# Evidence-Driven Decision Intelligence Platform

An AI workspace for **complex, evidence-driven decisions**.

The platform lets a user create an isolated decision workspace, ingest
research and business documents, retrieve evidence through a persistent
knowledge layer, ask questions, and run structured decision analyses.
Decisions are stored with evidence, claims, assumptions, risks,
alternatives, provenance, validation, freshness, comparison, and
reassessment support.


The project includes:

-   Workspace isolation
-   Document ingestion and provenance
-   Semantic retrieval
-   Optional knowledge-graph enrichment
-   Stateful LangGraph decision analysis
-   Structured evidence-backed recommendations
-   Decision history and persistence
-   Targeted reassessment
-   Decision comparison
-   Provenance tracing
-   Deterministic structural validation
-   Knowledge/decision freshness detection
-   React + TypeScript frontend
-   FastAPI backend
-   Local embedded Cognee storage
-   OpenRouter/OpenAI provider support
-   Local FastEmbed embeddings
-   Docker/Compose deployment
-   CORS and ingestion-path hardening
-   98 deterministic backend tests

------------------------------------------------------------------------

## 1. What problem does it solve?

Normal RAG systems are good at answering:

> **"What does my knowledge base say?"**

This project extends that idea to:

> **"Given the available evidence, what should I do, why, what are the
> risks and alternatives, and has new information changed the
> decision?"**

A workspace represents one decision domain, for example:

-   Should we enter the German solar market?
-   Can an E-buggy be implemented in rural India?
-   Should a company launch a new product?
-   Which market should receive investment?
-   Has newly published research invalidated an earlier conclusion?

The system keeps the evidence and decisions scoped to the workspace so
unrelated domains do not contaminate one another.

------------------------------------------------------------------------

# 2. Architecture

``` mermaid
flowchart TD
    U[Client] --> API[FastAPI]
    API --> WS[WorkspaceRegistry - JSON]
    API --> ING[IngestionService]
    API --> LG[LangGraph WorkspaceAgent]
    ING --> K[KnowledgeService]
    LG --> R[WorkspaceRetriever] --> K
    K --> C[Cognee adapter]
    C --> V[Embedded vector store]
    C --> G[Embedded graph store]
    C --> M[Session memory]
    LG --> O[OpenAI Responses API]
```

The application owns source normalization, retrieval coordination,
orchestration and HTTP schemas.

Cognee owns:

-   embeddings
-   graph construction
-   retrieval
-   persistent knowledge storage
-   session memory

LangGraph owns workflow state and execution.

The `KnowledgeService` protocol in `app/domain.py` is the boundary
between the application and knowledge layer. Production uses
`CogneeKnowledgeService`; tests use in-memory fakes.

------------------------------------------------------------------------

# 3. High-level data flow

``` text
Documents
   │
   ▼
IngestionService
   │
   ├── normalize source/provenance
   ├── validate paths
   └── send documents to Cognee
          │
          ├── embeddings/vector store
          ├── optional graph enrichment
          └── persistent knowledge
                    │
                    ▼
             WorkspaceRetriever
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
      semantic    graph     memory
       search     search     recall
          └─────────┼─────────┘
                    ▼
              LangGraph Agent
                    │
                    ▼
           Structured Decision
                    │
          ┌─────────┼────────────┐
          ▼         ▼            ▼
      decisions   Cognee     workspace
        .json     memory      metadata
```

Only structured application data and visible question/answer information
are persisted. Model reasoning traces are not stored.

------------------------------------------------------------------------

# 4. Decision-analysis workflow

A decision analysis is implemented as a typed LangGraph workflow:

``` text
START
  -> understand_decision
  -> retrieve_context
       | thin context?
       -> refine_retrieval
       -> retrieve_context       (at most once)
  -> retrieve_previous_decisions
  -> extract_evidence
  -> generate_claims
  -> identify_assumptions_and_risks
  -> evaluate_alternatives
  -> generate_recommendation
  -> persist_decision
  -> respond
END
```

Each LLM stage requests structured output validated against Pydantic
models.

If structured output is invalid, the workflow performs one corrective
retry. If it still fails, the request fails rather than inventing a
decision.

The resulting decision contains:

-   recommendation
-   rationale
-   confidence
-   evidence
-   claims
-   assumptions
-   risks
-   alternatives
-   sources
-   reassessment metadata

------------------------------------------------------------------------

# 5. Reassessment

A major feature is the ability to revisit an existing decision when new
knowledge arrives.

Example:

``` text
Decision A
    │
    ├── documents available at T1
    │
    ▼
New documents ingested at T2
    │
    ▼
Freshness detection
    │
    ▼
Decision A becomes stale
    │
    ▼
Targeted reassessment
    │
    ▼
Decision B
    ├── supersedes Decision A
    └── records what changed
```

The reassessment endpoint explicitly identifies the previous decision.
The agent puts that decision first among previous decisions so the
recommendation stage can evaluate it against current workspace
knowledge.

A normal new decision is not automatically anchored to an earlier
decision.

------------------------------------------------------------------------

# 6. Decision intelligence features

## Comparison

Compares two persisted decisions and reports changes in:

-   recommendation
-   confidence
-   status
-   evidence
-   claims
-   assumptions
-   risks
-   alternatives
-   supersession relationship

Evidence is matched using its statement rather than its per-run ID
because IDs such as `E1`, `E2`, etc. are local to an individual
analysis.

## Provenance

Provenance follows:

``` text
Recommendation
    ↓
Claims
    ↓
Evidence
    ↓
Source document
```

It does not invent missing relationships.

It explicitly reports:

-   unresolved evidence IDs
-   uncited evidence IDs

## Validation

Validation is deterministic and structural, not an LLM judge.

It checks:

-   claims reference existing evidence
-   evidence contains required fields
-   alternatives reference valid evidence
-   risk rationales reference valid evidence
-   reassessment metadata is consistent
-   provenance relationships are structurally valid

Structural problems are errors.

Quality concerns such as missing alternatives or missing rationale are
warnings.

## Freshness

Freshness compares:

``` text
decision.created_at
        vs
workspace.knowledge_updated_at
```

If knowledge was ingested after a decision was created, the decision can
be marked stale.

This check requires:

-   no LLM call
-   no retrieval
-   no embeddings

It is therefore cheap and deterministic.

------------------------------------------------------------------------

# 7. Ingestion

The ingestion layer is source-agnostic.

Supported sources include:

-   local Markdown/text files
-   text-readable PDFs
-   directories
-   inline documents
-   bounded read-only GitHub ingestion

Documents preserve metadata such as:

-   source
-   filename
-   document type
-   location
-   timestamp

Provenance is retained when content enters the knowledge layer.

## Secure local ingestion

Ingest paths are server-side paths. Every path is resolved and must
remain below `INGEST_ROOT`.

Examples outside the allowed root are rejected.

This prevents a client from using the ingestion API to request arbitrary
files from the server filesystem.

The Docker configuration pins the ingestion root to the bundled examples
directory by default.

------------------------------------------------------------------------

# 8. Cognee ingestion and graph enrichment

Cognee's full enrichment pipeline can be expensive because graph
extraction and summarization use the LLM.

Therefore ingestion defaults to the fast indexing path.

### Default ingestion

``` text
documents
   ↓
classification
   ↓
chunk extraction
   ↓
embeddings
   ↓
semantic retrieval available
```

No graph LLM enrichment is required.

### Optional graph enrichment

Graph construction can be requested per ingestion:

``` json
{
  "paths": ["./examples/solar"],
  "build_graph": true
}
```

or triggered later through:

``` text
POST /workspaces/{workspace_id}/graph
```

The concurrency limit is configurable through `COGNEE_CHUNKS_PER_BATCH`
and defaults to a conservative value suitable for free-tier models.

------------------------------------------------------------------------

# 9. Storage architecture

The project intentionally does **not** require Postgres or Neo4j.

Application state uses:

``` text
EDI_DATA_DIR/
├── workspaces.json
├── decisions.json
├── data/
└── system/
```

Cognee uses its embedded persistent stores for knowledge, graph,
vectors, and memory.

The decision store remains JSON because the project needs a lossless
structured representation of previous decisions for comparison and
reassessment. Cognee memory is complementary and optimized for retrieval
rather than exact schema round-tripping.

Writes to the application's JSON stores use an atomic temporary-file
replacement strategy.

For deployment, `/data` should be backed by persistent storage.

------------------------------------------------------------------------

# 10. LLM providers

The provider boundary lives in `app/config.py`.

OpenRouter is preferred when `OPENROUTER_API_KEY` is present. Otherwise
the application can use OpenAI.

Default OpenRouter model:

``` text
openai/gpt-oss-20b:free
```

For Cognee, OpenRouter is mapped through its generic/custom provider
configuration:

  Variable         Value
  ---------------- --------------------------------------
  `LLM_PROVIDER`   `custom`
  `LLM_MODEL`      `openrouter/openai/gpt-oss-20b:free`
  `LLM_ENDPOINT`   `https://openrouter.ai/api/v1`
  `LLM_API_KEY`    OpenRouter API key

Explicit environment variables take precedence over values derived by
the application.

------------------------------------------------------------------------

# 11. Embeddings

OpenRouter does not provide the embeddings endpoint used by this
application.

Two configurations are supported.

### OpenAI embeddings

Provide:

``` text
OPENAI_API_KEY=...
```

### Local FastEmbed

Install:

``` bash
pip install -e ".[local-embeddings]"
```

Then configure:

``` text
EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384
```

The Docker image includes the local-embedding extra so the deployed
container does not silently fall back to an unavailable embedding
provider.

------------------------------------------------------------------------

# 12. Backend setup

## Requirements

Recommended:

-   Python 3.11+
-   Node.js 20+
-   npm
-   Git

For real Cognee execution, install the Cognee extra.

### Windows

``` powershell
cd D:\projects\AI-KG-CV

python -m venv .venv
.venv\Scripts\activate

pip install -e ".[dev,cognee,local-embeddings]"
```

### Linux/macOS

``` bash
python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev,cognee,local-embeddings]"
```

Create environment configuration:

``` bash
cp .env.example .env
```

On PowerShell:

``` powershell
Copy-Item .env.example .env
```

Set the required API key:

``` text
OPENROUTER_API_KEY=your_key_here
```

Never commit `.env`.

------------------------------------------------------------------------

# 13. Run the backend

Activate the virtual environment first.

``` bash
uvicorn app.main:app --reload --workers 1
```

Backend:

``` text
http://localhost:8000
```

Health check:

``` text
GET /health
```

OpenAPI:

``` text
http://localhost:8000/docs
```

The embedded Cognee stores are single-process, so use one Uvicorn
worker.

------------------------------------------------------------------------

# 14. Frontend setup

The frontend is a React + TypeScript application built with Vite.

``` bash
cd web
npm install
```

Create:

``` text
web/.env
```

with:

``` text
VITE_API_BASE_URL=http://localhost:8000
```

Run development mode:

``` bash
npm run dev
```

The Vite server normally starts at:

``` text
http://localhost:5173
```

Production build:

``` bash
npm run build
```

This performs:

``` text
TypeScript check
      +
Vite production build
```

When `web/dist` exists, FastAPI can serve the frontend from the same
origin.

------------------------------------------------------------------------

# 15. Frontend capabilities

The UI provides the complete product flow:

### Workspaces

-   create workspace
-   list workspaces
-   open a workspace

### Workspace knowledge

-   view documents
-   ingest knowledge
-   view graph state
-   inspect freshness

### Knowledge chat

Ask questions against workspace knowledge and see retrieval
metadata/source information.

### Decision analysis

Submit a decision question and generate a structured evidence-backed
decision.

### Decision history

Review previous decisions and their status.

### Decision detail

Inspect:

-   recommendation
-   confidence
-   evidence
-   claims
-   assumptions
-   risks
-   alternatives
-   provenance
-   validation
-   freshness

### Reassessment

Re-run a selected decision against current workspace knowledge.

### Comparison

Compare two decisions and identify what changed.

The frontend contains no decision logic of its own. It is an API client
and presentation layer.

------------------------------------------------------------------------

# 16. API

## Workspace API

  Method   Endpoint                                 Purpose
  -------- ---------------------------------------- ------------------------
  GET      `/health`                                Liveness
  POST     `/workspaces`                            Create workspace
  GET      `/workspaces`                            List workspaces
  GET      `/workspaces/{workspace_id}`             Workspace details
  GET      `/workspaces/{workspace_id}/documents`   Workspace documents
  GET      `/workspaces/{workspace_id}/freshness`   Workspace freshness
  POST     `/workspaces/{workspace_id}/ingest`      Ingest knowledge
  POST     `/workspaces/{workspace_id}/graph`       Build graph enrichment
  POST     `/workspaces/{workspace_id}/chat`        Knowledge chat

## Decision API

  ----------------------------------------------------------------------------------------------------------------------------------
  Method                  Endpoint                                                                           Purpose
  ----------------------- ---------------------------------------------------------------------------------- -----------------------
  POST                    `/workspaces/{workspace_id}/decisions`                                             Run decision analysis

  GET                     `/workspaces/{workspace_id}/decisions`                                             Decision history

  GET                     `/workspaces/{workspace_id}/decisions/{decision_id}`                               Retrieve decision

  POST                    `/workspaces/{workspace_id}/decisions/{decision_id}/reassess`                      Reassess decision

  GET                     `/workspaces/{workspace_id}/decisions/{decision_id}/compare/{other_decision_id}`   Compare decisions

  GET                     `/workspaces/{workspace_id}/decisions/{decision_id}/provenance`                    Decision provenance

  GET                     `/workspaces/{workspace_id}/decisions/{decision_id}/validation`                    Structural validation

  GET                     `/workspaces/{workspace_id}/decisions/{decision_id}/freshness`                     Decision freshness
  ----------------------------------------------------------------------------------------------------------------------------------

All decision routes are workspace-scoped.

A decision belonging to another workspace is intentionally returned as
`404`, preventing cross-workspace ID disclosure.

------------------------------------------------------------------------

# 17. Example API workflow

Create a workspace:

``` bash
curl -X POST http://localhost:8000/workspaces \
  -H "Content-Type: application/json" \
  -d '{"name":"E-buggy Market Analysis","description":"Can this be implemented in rural India?"}'
```

Ingest documents:

``` bash
curl -X POST http://localhost:8000/workspaces/e-buggy-market-analysis/ingest \
  -H "Content-Type: application/json" \
  -d '{"paths":["./examples/ebuggy"]}'
```

Ask a knowledge question:

``` bash
curl -X POST http://localhost:8000/workspaces/e-buggy-market-analysis/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What are the major barriers to rural deployment?","session_id":"demo-1"}'
```

Run a decision:

``` bash
curl -X POST http://localhost:8000/workspaces/e-buggy-market-analysis/decisions \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo-1","question":"Can this be implemented in rural India?"}'
```

After new information is ingested, check freshness and reassess the
decision.

------------------------------------------------------------------------

# 18. Security and reliability

### Path confinement

Local ingestion is restricted to `INGEST_ROOT`.

### CORS

CORS uses an explicit allowlist:

``` text
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

The application does not use wildcard `*` CORS.

### Secrets

Secrets are loaded from environment variables.

The following must never be committed:

``` text
.env
API keys
local Cognee databases
decision data
frontend build artifacts
node_modules
```

### Rate limits

Provider rate-limit exceptions are translated into HTTP `429` responses.

When a provider supplies `Retry-After`, it is forwarded to the client.

### Timeouts

LLM and Cognee operations have configurable timeout boundaries.

------------------------------------------------------------------------

# 19. Docker deployment

The project includes:

``` text
Dockerfile
docker-compose.yml
.dockerignore
```

Build and start:

``` bash
docker compose up --build
```

The container:

1.  builds the React frontend
2.  installs backend dependencies
3.  includes local embeddings
4.  starts FastAPI
5.  serves the React application
6.  exposes port `8000`
7.  mounts persistent application/Cognee data

Open:

``` text
http://localhost:8000
```

Health:

``` text
http://localhost:8000/health
```

The deployment uses one worker because the embedded Cognee stores are
designed for single-process operation.

For any persistent deployment, `/data` must use persistent storage.
Otherwise application decisions and embedded knowledge can disappear
when the container is recreated.

------------------------------------------------------------------------

# 20. Production deployment considerations

The Docker configuration is suitable for a small demo or controlled
deployment.

Before exposing it to untrusted users, add:

-   authentication
-   authorization
-   HTTPS
-   rate limiting
-   production secret management
-   stronger request-size limits
-   persistent storage
-   monitoring/log aggregation
-   backups

The current workspace isolation is an **application-level data
boundary**, not a complete authentication/security boundary.

Without authentication, users who can reach the API are not prevented
from accessing workspace IDs they know.

------------------------------------------------------------------------

# 21. Testing

The backend test suite is deterministic and does not require live
LLM/Cognee calls.

Run:

``` bash
pytest -q
```

Current verified result:

``` text
98 passed
```

Additional checks:

``` bash
ruff check .
pip check
python -m compileall app
```

Frontend:

``` bash
cd web
npm run build
```

The production frontend build performs TypeScript validation before Vite
bundling.

The integration smoke testing performed during Phase 4 covered:

-   health
-   frontend serving
-   CORS
-   workspace creation
-   workspace retrieval
-   ingestion
-   ingestion path security
-   document listing
-   graph state
-   decision history
-   decision retrieval
-   provenance
-   validation
-   comparison
-   freshness
-   UTF-8 responses
-   workspace isolation
-   LLM error mapping

------------------------------------------------------------------------

# 22. Project structure

``` text
AI-KG-CV/
│
├── app/
│   ├── agent/              # LangGraph agent and answer generation
│   ├── api/                # Pydantic API models
│   ├── decisions/          # Decision analysis, storage, validation,
│   │                        # comparison, provenance, freshness
│   ├── ingestion/          # Source loading and path validation
│   ├── knowledge/          # Cognee integration
│   ├── workspaces/         # Workspace lifecycle/persistence
│   ├── config.py           # Environment/provider configuration
│   ├── container.py        # Application dependency wiring
│   ├── domain.py           # Domain models/protocol boundaries
│   └── main.py             # FastAPI application and routes
│
├── tests/
│   ├── fakes.py
│   └── ...
│
├── web/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── api.ts
│   │   ├── hooks.ts
│   │   ├── types.ts
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
│
├── examples/
│   └── solar/
│
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
└── pyproject.toml
```

------------------------------------------------------------------------

# 23. Design decisions

### Why LangGraph?

The decision process is naturally represented as explicit stateful
stages. LangGraph provides controlled execution, typed state, bounded
refinement and clear workflow boundaries.

### Why Cognee?

Cognee provides the knowledge-layer primitives needed for semantic
retrieval, graph retrieval and persistent memory without requiring a
separate vector database and graph database for this project.

### Why JSON for decisions?

Decision records are relatively small and read-mostly. Exact structured
records are more reliable for comparison and reassessment than trying to
reconstruct a Pydantic decision from LLM-mediated memory.

### Why no Postgres?

The current workload and architecture do not require a relational
database. Introducing Postgres would add operational complexity without
replacing Cognee's embedded knowledge stores.

### Why graph enrichment is optional?

Graph enrichment is LLM-intensive. Semantic chunk retrieval already
provides useful knowledge access, while graph enrichment can be enabled
when relationship-heavy reasoning is valuable.

------------------------------------------------------------------------

# 24. Current limitations

The project is feature-complete, but it is intentionally not a
large-scale production SaaS platform.

Current limitations include:

-   no built-in authentication
-   single-process embedded Cognee deployment
-   synchronous ingestion/decision requests
-   scanned PDFs require OCR/text extraction
-   no automated contradiction detection
-   no external research/search agent
-   no production CI/CD pipeline
-   GitHub ingestion is bounded and read-only
-   model confidence is the model's judgement, not a calibrated
    probability
-   failed analysis stages do not resume from a durable workflow
    checkpoint

These are product-scale limitations, not unfinished Phase 4
functionality.

------------------------------------------------------------------------

# 25. Future extensions

Potential future work includes:

1.  Contradiction detection between new evidence and existing claims
2.  External research/search connectors
3.  Authentication and role-based workspace access
4.  Background job execution for long-running analysis
5.  Production relational metadata storage
6.  CI/CD and automated deployment
7.  Observability and usage/cost tracking
8.  Decision approval workflows
9.  Evidence quality scoring
10. Automated alerts when important decisions become stale

These should be treated as future product evolution rather than
requirements for the current release.

------------------------------------------------------------------------

# 26. Recommended demo flow

For a clean demonstration:

``` text
1. Create workspace
        ↓
2. Upload/ingest research
        ↓
3. Inspect documents
        ↓
4. Ask knowledge questions
        ↓
5. Run a decision
        ↓
6. Inspect recommendation + evidence + risks
        ↓
7. Open provenance + validation
        ↓
8. Add new knowledge
        ↓
9. Check freshness
        ↓
10. Reassess
        ↓
11. Compare old vs new decision
```

A useful non-solar example is:

> **Workspace:** E-buggy Market Analysis\
> **Decision:** Can this be implemented in rural India?

This demonstrates that the system is domain-independent rather than
being tied to the bundled solar example.

------------------------------------------------------------------------

# 27. License / project status

This repository is an implementation of an evidence-driven decision
intelligence platform built around FastAPI, LangGraph, Cognee,
React/TypeScript and OpenAI-compatible LLM providers.

**Release status: Phase 4 complete.**

The current release should be considered a working local/demo deployment
and a foundation for a production deployment with authentication,
persistent infrastructure, monitoring and CI/CD added as required.
