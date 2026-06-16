# Wakubo Semantic Search

Wakubo Semantic Search is a multi-tenant semantic product discovery system built for Shopify stores. It uses **FastAPI** for the backend API layer, **PostgreSQL** for structured data, **Qdrant** for vector search, and **LiquidJS + Vanilla JavaScript** for storefront-side integration.

The goal of the project is to move beyond simple keyword search and enable **semantic retrieval**, so users can discover products based on meaning, intent, and contextual similarity rather than exact text matches.

## Why Wakubo?

Traditional Shopify storefront search often depends heavily on exact keywords, tags, or manually curated filters. That works for straightforward queries, but it breaks down when users search more naturally, such as:

- “minimal black office bag”
- “warm-toned modern lamp”
- “casual summer travel shirt”
- “elegant gift for a formal dinner”

Wakubo addresses this by transforming product data into vector embeddings and using Qdrant to retrieve semantically similar matches.

## Key Features

- Multi-tenant semantic search architecture for Shopify stores
- Separate Qdrant collection for each store owner
- FastAPI-based backend for search and orchestration
- PostgreSQL for store metadata, operational data, and control-plane logic
- Qdrant for vector similarity search
- LiquidJS + Vanilla JavaScript compatibility for Shopify integration
- Docker-based local infrastructure for PostgreSQL and pgAdmin
- Designed to support scalable catalog indexing and isolated store-level retrieval

## Architecture Overview

Wakubo is designed as a **multi-tenant semantic search backend**.

### Core Components

#### 1. FastAPI Backend
The FastAPI application acts as the orchestration layer. It is responsible for:

- Receiving semantic search requests
- Handling tenant/store-aware routing
- Connecting the application flow with PostgreSQL and Qdrant
- Returning relevant product matches to the frontend or Shopify integration layer

#### 2. PostgreSQL
PostgreSQL stores structured application data such as:

- Store metadata
- Tenant configuration
- Catalog-related relational data
- Indexing state and supporting records
- Operational and control-plane information

#### 3. Qdrant
Qdrant is used as the vector database for semantic retrieval.

A major design decision in Wakubo is **tenant isolation**:
- Each Shopify store owner gets a **distinct Qdrant collection**
- Product embeddings are stored only inside that store’s collection
- Search queries are executed only against the relevant tenant collection

This approach helps with:
- Clean store-level data isolation
- Reduced risk of cross-tenant retrieval leakage
- Easier debugging and scaling
- Better long-term SaaS maintainability

#### 4. Shopify Integration Layer
The semantic search results are intended to be consumed by Shopify-facing components through:

- LiquidJS
- Vanilla JavaScript
- Storefront widgets or custom theme integration

This keeps the user-facing experience lightweight while the backend handles the heavier retrieval logic.

## Semantic Search Flow

A typical Wakubo flow looks like this:

1. Product catalog data is prepared for indexing
2. Product content is converted into embeddings
3. Embeddings are stored in Qdrant under the store-specific collection
4. Structured metadata is maintained in PostgreSQL
5. A user submits a search query
6. The query is transformed and matched semantically against vectors in Qdrant
7. The backend returns the most relevant product results for that specific store

## Status

Wakubo is an actively evolving semantic search backend focused on Shopify use cases. The current architecture emphasizes multi-tenant vector retrieval, store-level isolation, and backend extensibility.

## Deployment

The backend has been deployed on Railway during development, while local infrastructure is managed with Docker Compose.

## Tech Stack

- **Backend:** FastAPI
- **Frontend / Integration:** LiquidJS, Vanilla JavaScript
- **Database:** PostgreSQL
- **Vector Database:** Qdrant
- **Infrastructure:** Docker
- **Deployment:** Railway
- **Admin / DB Inspection:** pgAdmin

## Local Infrastructure

The local infrastructure includes PostgreSQL and pgAdmin via Docker Compose.

```yaml
services:
  postgres:
    image: postgres:15
    container_name: wakubo-pg
    environment:
      POSTGRES_DB: wakubo_temp
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - wakubo_pgdata:/var/lib/postgresql/data

  pgadmin:
    image: dpage/pgadmin4
    container_name: wakubo-pgadmin
    environment:
      PGADMIN_DEFAULT_EMAIL: ${PGADMIN_DEFAULT_EMAIL}
      PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_DEFAULT_PASSWORD}
    ports:
      - "5050:80"
    depends_on:
      - postgres

volumes:
  wakubo_pgdata:
```

> **Important:** Do not hardcode real credentials in version-controlled files. Use environment variables or a local `.env` file instead.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/dinasenpai/wakubo-semantic-search.git
cd wakubo-semantic-search
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

For Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start local infrastructure

If your Docker Compose file is inside `wakubo-infra/`:

```bash
cd wakubo-infra
docker compose up -d
```

This will start:
- PostgreSQL on `localhost:5432`
- pgAdmin on `http://localhost:5050`

### 5. Configure environment variables

Create a `.env` file for your local setup.

Example:

```env
POSTGRES_PASSWORD=your_local_password
PGADMIN_DEFAULT_EMAIL=your_email@example.com
PGADMIN_DEFAULT_PASSWORD=your_pgadmin_password

DATABASE_URL=postgresql://postgres:your_local_password@localhost:5432/wakubo_temp
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

SHOPIFY_API_KEY=
SHOPIFY_API_SECRET=
SHOPIFY_STORE_DOMAIN=
```

### 6. Run the FastAPI application

```bash
uvicorn app.main:app --reload
```

> If your FastAPI entry point differs, replace `app.main:app` with the correct module path.

## Multi-Tenant Design

One of the most important parts of Wakubo is its multi-tenant strategy.

Instead of storing all product embeddings in one shared collection, Wakubo is designed so that:

- Each store owner has their own collection in Qdrant
- Each query is routed to the appropriate tenant collection
- Search stays isolated and relevant to that store’s catalog only

This is especially useful for Shopify ecosystems where different merchants need:
- Catalog separation
- Search relevance scoped to their own inventory
- Better operational control
- Cleaner scaling as tenants grow independently

## Use Cases

Wakubo can be used for:

- Semantic product search in Shopify storefronts
- AI-assisted product discovery
- Search widgets for e-commerce themes
- Better retrieval for natural-language shopping queries
- Foundation for future recommendation or conversational shopping systems

## Example Queries

Wakubo is intended to support natural-language product discovery, for example:

- “show me modern black sneakers for office casual”
- “minimal jewelry for a formal evening outfit”
- “warm lighting decor for a cozy bedroom”
- “travel-friendly backpack with a premium look”

These are the kinds of searches that semantic retrieval handles more effectively than exact keyword matching alone.

## Future Improvements

Potential next steps for the project include:

- Automated embedding pipelines for new/updated products
- Background sync jobs for catalog refresh
- Better ranking / reranking strategies
- Search analytics per tenant
- Personalization layers on top of semantic retrieval
- Improved observability for indexing and search performance
- Deeper Shopify app and extension integration

## Security Notes

- Never commit real passwords or API keys
- Keep secrets in environment variables
- Isolate tenant data carefully
- Validate tenant-aware routing before production rollout
- Monitor query and retrieval behavior across stores

## Project Vision

Wakubo Semantic Search is designed as a practical semantic retrieval layer for Shopify commerce. The long-term value of the project lies in combining **tenant-aware vector search**, **backend orchestration**, and **storefront integration** into a reusable search system that can power modern product discovery experiences.

## Author

Built by [@dinasenpai](https://github.com/dinasenpai)
