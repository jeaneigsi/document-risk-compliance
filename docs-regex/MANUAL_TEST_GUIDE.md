# Guide de Test Manuel (Max Coverage)

Ce guide te permet de tester manuellement un maximum de fonctionnalités pour maîtriser l'application.

## 1. Préparation Environnement

Depuis `backend-regex`:

```bash
cd /home/jean/projects/doctorat/projet-1/backend-regex
cp -n .env.example .env
```

Vérifie `.env`:
- `NEXT_PLAID_URL=http://localhost:8081` (important dans ton setup WSL)
- `OPENROUTER_API_KEY=...`
- `OCR_API_KEY=...`

## 2. Démarrage Services

Terminal A (Docker core stack):

```bash
cd /home/jean/projects/doctorat/projet-1/core-regx
docker compose up -d
docker compose ps
```

Tu dois voir:
- NextPlaid sur `8081`
- Redis sur `6379`
- MinIO sur `9000/9001`

Terminal B (API):

```bash
cd /home/jean/projects/doctorat/projet-1/backend-regex
.venv/bin/python -m uvicorn app.api.main:app --reload --port 8000
```

Terminal C (Worker Celery):

```bash
cd /home/jean/projects/doctorat/projet-1/backend-regex
.venv/bin/python -m celery -A workers.celery_app worker --loglevel=info
```

## 3. Sanity Checks

```bash
curl -s http://localhost:8000/health | jq
curl -s http://localhost:8000/api/v1/health | jq
curl -s http://localhost:8000/api/v1/info | jq
```

Attendu:
- `/health`: service alive
- `/api/v1/health`: `status=healthy|degraded`, composants OCR/MinIO
- `/api/v1/info`: endpoints disponibles

## 4. Golden Path End-to-End

### 4.1 Upload document

Prépare un PDF test:

```bash
cp /path/to/ton/test.pdf /tmp/test-doc.pdf
```

Upload:

```bash
UPLOAD=$(curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@/tmp/test-doc.pdf")
echo "$UPLOAD" | jq
DOC_ID=$(echo "$UPLOAD" | jq -r '.document_id')
echo "$DOC_ID"
```

### 4.2 Poll status

```bash
curl -s "http://localhost:8000/api/v1/documents/$DOC_ID/status" | jq
```

Répète jusqu’à `status=completed`.

### 4.3 Lire contenu OCR extrait

```bash
curl -s "http://localhost:8000/api/v1/documents/$DOC_ID/content" | jq
```

Vérifie:
- `markdown` non vide
- `num_pages` cohérent
- `num_elements` cohérent

### 4.4 Détection incohérences

```bash
curl -s -X POST http://localhost:8000/api/v1/detect \
  -H "Content-Type: application/json" \
  -d "{
    \"document_id\": \"$DOC_ID\",
    \"claims\": [
      \"Le budget approuvé est de 1200 EUR au 2026-03-25\",
      \"Référence REF-AAA01\"
    ]
  }" | jq
```

Vérifie:
- `conflict_count`
- `severity`
- `recommendation`
- `results[].compression_ratio`
- `economics` (tokens/coût/appels LLM si déclenchés)

## 5. Search (hybrid/semantic/lexical)

### 5.1 Indexation manuelle d’evidence units

```bash
curl -s -X POST http://localhost:8000/api/v1/search/index \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "contracts",
    "evidence_units": [
      {
        "evidence_id": "ev-1",
        "document_id": "doc-a",
        "content": "Delivery deadline is 2026-04-01.",
        "source_type": "text_span",
        "page_number": 1,
        "metadata": {"section": "planning"}
      },
      {
        "evidence_id": "ev-2",
        "document_id": "doc-b",
        "content": "Budget approved amount is 900 EUR.",
        "source_type": "text_span",
        "page_number": 2,
        "metadata": {"section": "finance"}
      }
    ]
  }' | jq
```

### 5.2 Requêtes search

Hybrid:

```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"delivery deadline","index_name":"contracts","top_k":5,"strategy":"hybrid"}' | jq
```

Semantic:

```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"budget approved","index_name":"contracts","top_k":5,"strategy":"semantic"}' | jq
```

Lexical:

```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"delivery deadline","index_name":"contracts","top_k":5,"strategy":"lexical"}' | jq
```

Vérifie:
- `latency_ms`
- `candidate_count`
- `candidate_kept_count`
- qualité/ranking des `results`

## 6. LLM Direct

```bash
curl -s -X POST http://localhost:8000/api/v1/llm/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "prompt":"Analyze this inconsistency: budget is 1200 in claim and 900 in source.",
    "model":"openrouter/google/gemini-2.0-flash-001"
  }' | jq
```

Vérifie:
- `content` utile
- `usage.prompt_tokens` / `usage.completion_tokens`

## 7. Evaluation Framework (Phase 7)

### 7.1 Eval recherche

```bash
curl -s -X POST http://localhost:8000/api/v1/eval/search \
  -H "Content-Type: application/json" \
  -d '{
    "strategy":"baseline",
    "top_k":5,
    "corpus":[
      {"id":"doc-1","text":"delivery deadline approved"},
      {"id":"doc-2","text":"budget update only"}
    ],
    "samples":[
      {
        "sample_id":"s1",
        "query":"delivery deadline",
        "relevant_ids":["doc-1"],
        "relevance_by_id":{"doc-1":1.0},
        "index_name":"default"
      }
    ]
  }' | jq
```

### 7.2 Eval détection

```bash
curl -s -X POST http://localhost:8000/api/v1/eval/detection \
  -H "Content-Type: application/json" \
  -d '{"gold_labels":[true,false,true,false],"predicted_labels":[true,false,false,false]}' | jq
```

### 7.3 Eval economics

```bash
curl -s -X POST http://localhost:8000/api/v1/eval/economics \
  -H "Content-Type: application/json" \
  -d '{
    "runs":[
      {"prompt_tokens":100,"completion_tokens":20,"cost_usd":0.01,"latency_ms":300,"compression_ratio":0.4,"llm_calls":1},
      {"prompt_tokens":200,"completion_tokens":40,"cost_usd":0.02,"latency_ms":500,"compression_ratio":0.5,"llm_calls":2}
    ]
  }' | jq
```

## 8. Tests Erreurs (indispensables)

### Upload

- Extension non supportée:

```bash
curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@/etc/hosts;filename=test.txt" | jq
```

- Fichier trop gros (>50MB en PDF).

### Content/Status

- `DOC_ID` inexistant:

```bash
curl -s "http://localhost:8000/api/v1/documents/does-not-exist/status" | jq
curl -s "http://localhost:8000/api/v1/documents/does-not-exist/content" | jq
```

### Detect

- `document_id` inexistant:

```bash
curl -s -X POST http://localhost:8000/api/v1/detect \
  -H "Content-Type: application/json" \
  -d '{"document_id":"missing","claims":["x"]}' | jq
```

### Eval

- Taille labels différente:

```bash
curl -s -X POST http://localhost:8000/api/v1/eval/detection \
  -H "Content-Type: application/json" \
  -d '{"gold_labels":[true],"predicted_labels":[true,false]}' | jq
```

## 9. Tests Worker/Celery Manuels

Ping worker:

```bash
.venv/bin/python - <<'PY'
from workers.celery_app import health_check_task
r = health_check_task.delay()
print(r.get(timeout=10))
PY
```

Lancer éval search async:

```bash
.venv/bin/python - <<'PY'
from workers.tasks import run_eval_search
r = run_eval_search.delay(
    samples=[{
        "sample_id":"s1",
        "query":"delivery deadline",
        "relevant_ids":["doc-1"],
        "relevance_by_id":{"doc-1":1.0},
        "index_name":"default"
    }],
    corpus=[{"id":"doc-1","text":"delivery deadline approved"}],
    strategy="baseline",
    top_k=5
)
print(r.get(timeout=20))
PY
```

## 10. Contrôle Persistance (MinIO)

Console MinIO: `http://localhost:9001`

Vérifie:
- bucket `documents`: fichier uploadé
- bucket `extracted`: `markdown`, `layout`, `metadata`
- suppression via API retire les objets

## 11. Checklist Maîtrise

Tu maîtrises l’app si tu sais:
- Démarrer API + worker + stack Docker sans erreur.
- Uploader un document et suivre son cycle complet.
- Expliquer la différence `search` entre `lexical`, `semantic`, `hybrid`.
- Interpréter `severity`, `conflict_count`, `compression_ratio`, `economics`.
- Lancer et interpréter les endpoints d’évaluation phase 7.
- Reproduire 4 erreurs contrôlées (upload, detect, content, eval labels).
- Vérifier la persistance MinIO et le traitement async Celery.
