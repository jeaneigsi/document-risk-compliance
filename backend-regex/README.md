# Backend Regex - Docs Inconsistency Detection

Backend FastAPI pour la détection d'incohérences documentaires avec LLM.

## Architecture

```
core-regx/
├── docker-compose.yml        # NextPlaid + Redis + MinIO
└── backend-regex/
    ├── app/                  # Application FastAPI
    │   ├── api/              # Routes API
    │   ├── ingest/           # OCR, parsing, S3 storage (Phase 2)
    │   ├── search/           # Recherche NextPlaid (Phase 3)
    │   ├── detect/           # Détection (Phase 4)
    │   ├── llm/              # LLM client (Phase 5)
    │   ├── monitor/          # Observabilité (Phase 6)
    │   └── eval/             # Framework d'évaluation (Phase 7)
    ├── workers/              # Celery tasks
    └── tests/                # Tests pytest
```

## Installation

### Prérequis

- Python 3.12+
- Docker & Docker Compose
- uv (package manager)

### Démarrage rapide

```bash
# 1. Démarrer Docker (NextPlaid + Redis + MinIO)
cd ../core-regx
docker compose up -d

# 2. Installer les dépendances Python
cd ../backend-regex
uv sync

# 3. Configurer l'environnement
cp .env.example .env
# Éditer .env avec vos clés API (Z.ai OCR, OpenRouter)

# 4. Lancer l'API
uv run uvicorn app.api.main:app --reload

# 5. Lancer le worker (terminal séparé)
uv run celery -A workers.celery_app worker --loglevel=info
```

## Services Docker

| Service | Port | Description |
|---------|------|-------------|
| NextPlaid | 8081 | Recherche sémantique |
| Redis | 6379 | Broker Celery |
| MinIO | 9000, 9001 | Stockage S3 (API + Console) |

**MinIO Console**: http://localhost:9001 (minioadmin / minioadmin123)

## Tests

```bash
# Lancer tous les tests
uv run pytest

# Avec coverage
uv run pytest --cov=app --cov=workers

# Mode verbose
uv run pytest -v
```

Guide de test manuel complet:
- `docs/MANUAL_TEST_GUIDE.md`
- `docs/postman/` (collection Postman classée)
- `docs/APP_USAGE_SCENARIOS.md` (scénarios d'utilisation complets)

## API Endpoints

### Health & Info
- `GET /api/v1/health` - État des services
- `GET /api/v1/info` - Informations API

### Documents (Phase 2)
- `POST /api/v1/documents/upload` - Upload document
- `GET /api/v1/documents/{id}/status` - Statut traitement
- `GET /api/v1/documents/{id}/content` - Contenu extrait
- `DELETE /api/v1/documents/{id}` - Supprimer document

### Search (Phase 3)
- `POST /api/v1/search` - Recherche sémantique dans l'index
- `POST /api/v1/search/index` - Indexation d'evidence units

`/api/v1/search` supporte `strategy`:
- `hybrid` (défaut): fusion lexical (cursor-like) + sémantique (NextPlaid)
- `semantic`: NextPlaid uniquement
- `lexical`: index local trigrammes + inversé uniquement

### Detection (Phase 4)
- `POST /api/v1/detect` - Détection d'incohérences sur document extrait

### LLM (Phase 5)
- `POST /api/v1/llm/analyze` - Analyse d'un prompt via LiteLLM/OpenRouter

### Évaluation (Phase 7)
- `POST /api/v1/eval/search` - Métriques recherche (Recall@k, MRR, nDCG)
- `POST /api/v1/eval/detection` - Métriques détection (Precision, Recall, F1)
- `POST /api/v1/eval/economics` - Métriques économiques (tokens, coût, latence)

## Configuration

Variables d'environnement (voir `.env.example`) :

```bash
# Services
NEXT_PLAID_URL=http://localhost:8081    # NextPlaid
REDIS_URL=redis://localhost:6379/0      # Redis

# OCR (Z.ai)
OCR_API_KEY=your_zai_api_key

# Stockage MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123

# LLM (OpenRouter)
OPENROUTER_API_KEY=your_openrouter_api_key
```

## Buckets MinIO

- `documents` - Fichiers originaux uploadés
- `extracted` - Contenu OCR (markdown, layout JSON)
- `cache` - Fichiers temporaires

## Développement

### Phase 8 (expériences sur machine modeste)

Le module `app.eval.datasets` supporte un mode `streaming=True` pour éviter de charger des datasets complets en RAM/disque.

Variables recommandées:

```bash
export HF_HOME=$HOME/.cache/huggingface
export HF_DATASETS_CACHE=$HOME/.cache/huggingface/datasets
```

### Structure des tests

```
tests/
├── conftest.py       # Fixtures partagées
├── test_config.py    # Configuration
├── test_api.py       # Endpoints API
├── test_workers.py   # Tâches Celery
└── test_ocr.py       # Client OCR
```

### Coverage target

> 80% minimum

## Phases d'implémentation

1. ✅ **Phase 1** - Infrastructure & Structure
2. 🚧 **Phase 2** - OCR & Parsing (MinIO + Z.ai)
3. **Phase 3** - Recherche Documentaire (4 semaines)
4. **Phase 4** - Détection Incohérences (4 semaines)
5. **Phase 5** - LLM Integration (4 semaines)
6. **Phase 6** - Observabilité (4 semaines)
7. **Phase 7** - Evaluation Framework (4 semaines)
8. **Phase 8** - Expériences Scientifiques (6 semaines)
9. **Phase 9** - Rédaction (4 semaines)

# Launch 

1. activer env "v" , installer dep "vs"
2. python -m celery -A workers.celery_app worker --loglevel=info
2. python -m uvicorn app.api.main:app --reload --port 8000
