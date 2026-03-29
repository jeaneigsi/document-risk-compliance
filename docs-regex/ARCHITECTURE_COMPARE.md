# Architecture du Pipeline de Comparaison Documentaire

> Analyse complète de l'architecture et du fonctionnement du système de comparaison DocVerify.

---

## 1. Vue d'ensemble

Le système compare deux documents (PDF, scans) et détecte les changements significatifs entre eux via un pipeline multi-étapes : ingestion, recherche de preuves, appariement, diff lexical, et synthèse LLM.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        FLUX COMPLET                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Frontend (Vue 3)                                                      │
│  ┌──────────────┐    ┌───────────────────┐    ┌──────────────────┐    │
│  │ CompareDocs  │───→│ POST /compare/runs │───→│ CompareResult    │    │
│  │ (setup)      │    │ (crée un run)      │    │ (résultats)      │    │
│  └──────────────┘    └─────────┬─────────┘    └──────────────────┘    │
│                                │                                        │
│  Backend (FastAPI)             ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                CompareDocumentsPipeline                          │  │
│  │                                                                  │  │
│  │  1. prepare_document() ─→ PreparedDocument (md + layout + EU)   │  │
│  │  2. _discover_changes() ─→ SearchPipeline ─→ Evidence rows      │  │
│  │  3. pair_evidence_rows() ─→ Paires alignées A/B                  │  │
│  │  4. LexicalDiffEngine  ─→ Diff ops (insert/delete/equal)        │  │
│  │  5. _group_changes()   ─→ Changements structurés                 │  │
│  │  6. _decide_from_pairs()─→ LLM synthesis ─→ Résumé              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. API REST

### Endpoints

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/v1/compare/analyze` | Comparaison synchrone (bloquante) |
| `POST` | `/api/v1/compare/runs` | Crée un run asynchrone |
| `GET` | `/api/v1/compare/runs` | Liste les runs récents (`?limit=20`) |
| `GET` | `/api/v1/compare/runs/{run_id}` | Récupère un run par ID |

### Modèles de données

**Requête** (`CompareAnalyzeRequest`) :
```python
{
    "left_document_id": "abc-123",
    "right_document_id": "def-456",
    "model": "openrouter/qwen/qwen3.5-9b:exacto",  # optionnel
    "index_name": "default",                          # default | documents | evidence
    "strategy": "hybrid",                             # hybrid | semantic | lexical | rg
    "compare_mode": "standard"                        # standard | adaptive | full_lexical
}
```

**Réponse run** (`CompareRunDetailResponse`) :
```python
{
    "run_id": "uuid",
    "created_at": "ISO-8601",
    "updated_at": "ISO-8601",
    "status": "pending | processing | completed | failed",
    "left_document_id": "...",
    "right_document_id": "...",
    "strategy": "hybrid",
    "index_name": "default",
    "model": "...",
    "config": {},
    "result": { ... }   # null si encore en cours
}
```

### Persistance (SQLite)

Table `compare_runs` :

| Colonne | Type | Description |
|---------|------|-------------|
| `run_id` | TEXT PK | UUID du run |
| `created_at` | TEXT | Date de création ISO-8601 |
| `updated_at` | TEXT | Dernière mise à jour |
| `status` | TEXT | pending / processing / completed / failed |
| `left_document_id` | TEXT | ID document A |
| `right_document_id` | TEXT | ID document B |
| `strategy` | TEXT | Stratégie de recherche utilisée |
| `index_name` | TEXT | Index utilisé |
| `model` | TEXT | Modèle LLM |
| `config_json` | TEXT | Configuration sérialisée JSON |
| `result_json` | TEXT | Résultat sérialisé JSON |
| `error_text` | TEXT | Message d'erreur si failed |

---

## 3. Module Compare (`app/compare/`)

### 3.1 Pipeline principal (`pipeline.py`)

#### Classe `PreparedDocument`

```python
@dataclass
class PreparedDocument:
    document_id: str
    filename: str
    markdown: str           # Contenu texte extrait
    layout: list            # Métadonnées de layout (pages, blocs, tables)
    evidence_units: list    # EvidenceUnit indexables
```

#### Classe `CompareDocumentsPipeline`

**Constructeur** :
```python
CompareDocumentsPipeline(
    search_pipeline: SearchPipeline | None = None,
    llm_client: LiteLLMClient | None = None,
    diff_engine: LexicalDiffEngine | None = None,
)
```

**Méthode principale** `analyze()` :

```python
async def analyze(
    left: PreparedDocument,
    right: PreparedDocument,
    claims: list[str] | None = None,
    strategy: str = "hybrid",
    index_name: str = "default",
    model: str | None = None,
    compare_mode: str = "standard",
) -> dict[str, Any]
```

**Modes de comparaison** :

| Mode | Comportement |
|------|-------------|
| `standard` | Diff-first avec retrieval grounding (défaut) |
| `full_lexical` | Comparaison lexicale exhaustive |
| `adaptive` | Combine standard + fenêtrage adaptatif (max 8 fenêtres) |

**Flux interne** :

```
analyze()
  │
  ├─→ _analyze_claim_driven()    # Si claims fournis
  │     → Pour chaque claim: retrieve, pair, decide
  │
  └─→ _analyze_diff_first()     # Par défaut
        │
        ├─→ _discover_changes()
        │     ├─→ _retrieve_for_document(left)
        │     │     └─→ SearchPipeline.run() → evidence rows
        │     ├─→ _retrieve_for_document(right)
        │     │     └─→ SearchPipeline.run() → evidence rows
        │     ├─→ pair_evidence_rows() → paires alignées
        │     └─→ _build_evidence_row() → formatage
        │
        ├─→ _group_changes() → regroupement par thème
        │
        └─→ _decide_from_pairs() → décision + LLM summary
```

#### Sous-méthodes

| Méthode | Rôle |
|---------|------|
| `prepare_document()` | Extrait markdown, layout, evidence units d'un document |
| `_analyze_diff_first()` | Approche par défaut : découvre les changements automatiquement |
| `_analyze_claim_driven()` | Analyse ciblée sur des claims spécifiques |
| `_discover_changes()` | Recherche bidirectionnelle + appariement |
| `_discover_changes_full_lexical()` | Scan lexical complet entre les deux docs |
| `_group_changes()` | Regroupe les changements par catégorie/thème |
| `_retrieve_for_document()` | Lance le SearchPipeline sur un document |
| `_build_evidence_row()` | Formate un résultat de recherche en evidence row |
| `_decide_from_pairs()` | Prend une décision à partir des paires + LLM |
| `_build_compare_prompt()` | Construit le prompt LLM pour la comparaison |

---

### 3.2 Moteur de diff (`diff_engine.py`)

#### Classe `LexicalDiffEngine`

```python
class LexicalDiffEngine:
    def diff_words(text_a: str, text_b: str) -> list[dict[str, str]]
    def classify_change(text_a: str, text_b: str, diff_ops) -> str
```

**Opérations de diff** : chaque op est un dict `{ "op": "insert"|"delete"|"equal", "text": "..." }`

**Classification des changements** :

| Type | Description |
|------|-------------|
| `numeric_change` | Modification d'un montant ou chiffre |
| `date_change` | Modification d'une date |
| `reference_change` | Modification d'une référence (REF, ID) |
| `clause_change` | Modification d'une clause juridique |
| `semantic_change` | Changement sémantique général |

**Patterns regex utilisés** :
- `NUMBER_RE` : Valeurs numériques avec devises (€, EUR, USD, $, MAD)
- `DATE_RE` : Formats de dates
- `REF_RE` : Identifiants de référence (ex: REF12345)

---

### 3.3 Normalisation (`normalization.py`)

| Fonction | Entrée | Sortie | Rôle |
|----------|--------|--------|------|
| `normalize_text(text)` | Texte brut | Texte normalisé | Nettoyage uniforme |
| `detect_claim_category(claim)` | Claim string | Catégorie | Classification (amount, date, duration, reference, etc.) |
| `extract_facts(text, category)` | Texte + catégorie | `list[dict]` | Extraction de faits structurés |
| `extract_section_hint(text)` | Texte | Section hint | Indice de section (ex: "Section 3") |
| `select_facts_for_category(text, category)` | Texte + catégorie | `list[dict]` | Sélectionne les faits pertinents |

**Champs structurés de confiance** : `{"amount", "date", "duration", "reference", "jurisdiction"}`

---

### 3.4 Appariement (`pairing.py`)

```python
def pair_evidence_rows(
    claim: str,
    category: str,
    left_rows: list[dict],
    right_rows: list[dict],
    max_pairs: int = 3,
    score_threshold: float = 0.5,
) -> list[dict]:
```

**Algorithme de scoring** :
- Match exact texte : +0.5
- Similarité difflib (≥ 0.55) : score += similarité × 1.5
- Retourne les paires triées par score descendant

---

### 3.5 Historique (`history.py`)

#### Classe `CompareRunRepository`

```python
class CompareRunRepository:
    def __init__(self, db_path: str | None = None)
    def create_run(...) -> dict              # INSERT en base
    def get_run(run_id: str) -> dict | None  # SELECT par PK
    def list_runs(limit: int = 20) -> list   # SELECT récents
    def update_run(run_id, ...) -> dict      # UPDATE status/result
```

---

## 4. Pipeline de Recherche (`app/search/`)

### 4.1 SearchPipeline (`pipeline.py`)

```python
class SearchPipeline:
    def __init__(self, client: NextPlaidClient, registry: LocalSearchRegistry)

    async def run(
        query: str,
        index_name: str = "default",
        top_k: int = 10,
        strategy: str = "hybrid",
        document_ids: list[str] | None = None,
    ) -> dict
```

**Routage par stratégie** :

| Stratégie | Recherche sémantique | Recherche lexicale | Fusion |
|-----------|---------------------|--------------------|----|
| `baseline` | Non | Non | — (retourne vide) |
| `lexical` | Non | Oui (`registry.lexical_search`) | — |
| `semantic` | Oui (`NextPlaidClient.search`) | Non | — |
| `hybrid` | Oui | Oui | `fuse_search_results()` |
| `rg` | Non | Oui (`registry.rg_search`) | — |

**Pour `hybrid`**, le top_k sémantique interne est `max(12, top_k + 2)` pour élargir le candidat pool avant fusion.

### 4.2 Index Cursor-like (`cursor_like.py`)

Trois classes composables :

#### `TrigramIndex`
- Construit un index de trigrammes (3-grams) pour chaque document
- Recherche : AND sur les trigrammes de la query → candidats
- Score : ratio de chevauchement trigramme

#### `InvertedIndex`
- Index inversé classique (token → doc_ids)
- Score TF-IDF

#### `CursorLikeIndex` (composite)
```python
class CursorLikeIndex:
    def add_documents(documents)
    def search(query, top_k)        # Combiné trigram + inverted
    def rg_search(query, top_k)     # Regex full-scan
```

**Formule de score** pour `search()` :
```
score = 0.55 × trigram_score + 0.35 × token_score + 0.10 × phrase_bonus
```

### 4.3 Client NextPlaid (`nextplaid_client.py`)

```python
class NextPlaidClient:
    def health_check() -> bool
    def search(query, index_name, top_k, document_ids, filters) -> list[dict]
    def index_evidence_units(evidence_units, index_name) -> dict
    def create_index(index_name, nbits=4) -> dict
    def delete_documents(filter_condition, filter_parameters) -> dict
```

- Communication via HTTP vers le service NextPlaid (Docker)
- Encodage multi-vector intégré (ColGREP)
- Endpoint principal : `POST /indices/{index_name}/search_with_encoding`

### 4.4 Ranking (`ranking.py`)

#### `rank_search_results(semantic_results, top_k)`
Tri simple par score décroissant.

#### `fuse_search_results(semantic, lexical, top_k=10, semantic_weight=0.55, lexical_weight=0.45)`

**Algorithme RRF (Reciprocal Rank Fusion) adapté** :
1. Normalisation min-max des scores → [0, 1]
2. Pour chaque résultat :
   - `score = score_norm × 0.65 + rank_component × 0.35`
   - `rank_component = 1 / (60 + rank)`
3. Combinaison pondérée par `semantic_weight` / `lexical_weight`
4. Bonus de +0.08 pour les documents présents dans les deux listes
5. Tri final par score fusionné, retour top_k

### 4.5 Plannificateur Regex (`regex_planner.py`)

Construit des plans de requête regex optimisés avec clauses de trigrammes multiples. Supporte le filtrage par patterns regex avec trigram indexing pour la performance.

### 4.6 Client d'Embeddings (`embedding_client.py`)

```python
class EmbeddingClient:
    async def embed_texts(texts: list[str]) -> list[list[float]]
```

- Utilise LiteLLM → OpenRouter pour générer les embeddings
- Configurable : modèle, dimensions, base_url

### 4.7 Registre Local (`local_registry.py`)

```python
class LocalSearchRegistry:
    def add_evidence_units(index_name, evidence_units)
    def lexical_search(index_name, query, top_k, document_ids) -> list
    def rg_search(index_name, query, top_k, document_ids) -> list
```

Maintient un `dict[str, CursorLikeIndex]` — un index par nom logique.

### 4.8 Evidence Units (`evidence.py`)

```python
class EvidenceUnit:
    evidence_id: str
    document_id: str
    content: str
    source_type: str = "text_span"
    page_number: int | None
    metadata: dict
```

**Constructeurs** :
- `map_find_to_evidence_units(record, document_id)` — depuis dataset FIND
- `build_evidence_units_from_ocr(document_id, filename, md_results, layout)` — depuis OCR

---

## 5. Pipeline de Détection (`app/detect/`)

> Note : Ce module est utilisé pour la détection d'incohérences classique (Phase 4). Le pipeline de comparaison (`app/compare/`) a sa propre logique de détection intégrée.

### 5.1 DetectionPipeline (`pipeline.py`)

```python
class DetectionPipeline:
    async def run(
        document_id: str,
        claims: list[str],
        markdown: str,
        layout: list | None = None,
    ) -> dict
```

**Flux** :
1. Découpe le markdown en 8 snippets max
2. Pour chaque claim :
   - Détecteurs déterministes (date, montant, référence)
   - Comparateurs (clause, table, section)
   - Si sévérité high/critical → appel LLM
   - Construit un `MinimalContextBundle`
3. Agrège les conflits → score de sévérité global

### 5.2 Détecteurs déterministes (`deterministic.py`)

| Classe | Pattern | Sévérité |
|--------|---------|----------|
| `DateConflictDetector` | `DATE_RE` (YYYY-MM-DD, DD/MM/YY) | high |
| `AmountConflictDetector` | `AMOUNT_RE` (€, EUR, USD, $, MAD) | critical |
| `ReferenceMismatchDetector` | `REF_RE` (REF, ID) | medium |

### 5.3 Comparateurs (`comparators.py`)

| Classe | Entrée | Algorithme | Seuil conflit |
|--------|--------|------------|---------------|
| `ClauseComparator` | claim vs evidence | SequenceMatcher + négation | ratio > 0.35 + négation mismatch |
| `TableComparator` | nombres A vs B | Intersection d'ensembles | Ensembles disjoints |
| `SectionComparator` | section A vs B | SequenceMatcher | ratio < 0.75 |

**Marqueurs de négation** : `{"not", "no", "never", "none", "without", "aucun", "pas"}`

### 5.4 Compression (`compression.py`)

```python
class MinimalContextBundle:
    claim: str
    snippets: list[str]
    max_chars: int = 1200

    @property
    def text(self) -> str           # claim + snippets, tronqué à max_chars
    @property
    def compression_ratio(self) -> float  # len(text) / total_original
```

```python
def build_minimal_context(claim, evidence_snippets, max_chars=1200) -> MinimalContextBundle
```

Algorithme glouton : sélectionne les snippets les plus courts jusqu'à atteindre `max_chars`.

### 5.5 Décision (`decision.py`)

**Scoring de sévérité** :

| Poids par type | Valeur |
|----------------|--------|
| amount | 4 |
| date | 3 |
| reference / clause | 2 |
| autres | 1 |

**Règles** :
- `critical` : max_hint ≥ 4 OU weighted ≥ 8
- `high` : max_hint ≥ 3 OU weighted ≥ 5
- `medium` : max_hint ≥ 2 OU weighted ≥ 2
- `low` : sinon

---

## 6. Client LLM (`app/llm/`)

### 6.1 LiteLLMClient (`litellm_client.py`)

```python
class LiteLLMClient:
    def __init__(self)  # Configure API key, base_url, model, timeout, pricing

    async def analyze(
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict  # { status, model, content, usage: { prompt_tokens, completion_tokens } }

    def analyze_sync(...)  # Version synchrone

    def estimate_cost(usage, input_price, output_price) -> float  # Coût USD
```

- Utilise `litellm.acompletion()` / `litellm.completion()`
- Model-agnostic via OpenRouter

### 6.2 Prompts (`prompts.py`)

| Fonction | Rôle |
|----------|------|
| `build_detection_prompt(claim, context, conflicts)` | Prompt d'analyse d'incohérence |
| `build_explanation_prompt(result)` | Résumé en ≤5 bullet points |
| `build_summary_prompt(results)` | Synthèse exécutive multi-résultats |

**Schéma JSON attendu du LLM** :
```json
{
    "verdict": "consistent | inconsistent | uncertain",
    "confidence": 0.0-1.0,
    "rationale": "explication courte",
    "recommended_action": "..."
}
```

---

## 7. Monitoring (`app/monitor/`)

### 7.1 Langfuse (`langfuse.py`)

```python
class LangfuseTracker:
    def __init__()            # Auto-detect si clés présentes
    def trace(name, input, metadata) -> str   # Crée une trace
    def event(trace_id, name, output, metadata) # Ajoute un événement
```

- Fallback safe si clés absentes (no-op)
- `flush()` appelé après chaque trace/event
- Singleton via `get_langfuse_tracker()`

### 7.2 OpenTelemetry (`telemetry.py`)

```python
def get_tracer() -> Tracer       # Retourne un tracer OTel ou no-op
def start_span(name, attributes) # Context manager pour les spans
```

---

## 8. Frontend

### 8.1 Parcours utilisateur

```
/compare (CompareDocsView)
  │
  ├─ Upload documents (gauche/droite)
  ├─ Polling jusqu'à status=completed
  ├─ Config: model, strategy, index, compare_mode
  └─ POST /compare/runs → redirect vers /compare/result/:runId
       │
       ▼
/compare/result/:runId (CompareResultView)
  │
  ├─ GET /compare/runs/:runId (polling si pending/running)
  ├─ GET /documents/:id/layout (pour rendu PDF)
  ├─ Affichage: changements, PDFs côte à côte, highlights
  └─ Relance possible avec autre stratégie
```

### 8.2 State management

**Session stockée dans `localStorage`** (`docs-regex.compare-session`) :

```javascript
{
    runId, status, result,
    leftDocument, rightDocument,
    leftDocumentId, rightDocumentId,
    model, indexName, strategy, compareMode,
    leftLayout, rightLayout
}
```

### 8.3 API frontend (`services/api.js`)

```javascript
compareApi = {
    analyze: (payload) => POST('/compare/analyze', payload),
    createRun: (payload) => POST('/compare/runs', payload),
    getRun: (runId) => GET(`/compare/runs/${runId}`),
    listRuns: (limit) => GET('/compare/runs', { params: { limit } }),
}
```

---

## 9. Infrastructure

| Service | Technologie | Rôle |
|---------|------------|------|
| Backend API | FastAPI + Uvicorn | REST API synchrone |
| Workers | Celery + Redis | Tâches asynchrones (OCR, indexing) |
| Recherche sémantique | NextPlaid (Docker) | Multi-vector search + ColGREP |
| Cache/Queue | Redis | Celery broker + cache |
| Stockage objet | MinIO S3 | Documents PDF, fichiers extraits |
| Base locale | SQLite | Persistance des runs de comparaison |
| LLM | OpenRouter (LiteLLM) | Analyse, synthèse, détection |
| Monitoring | Langfuse + OpenTelemetry | Traces, métriques, coûts |
| Frontend | Vue 3 + Vuetify + Pinia | Interface utilisateur |

---

## 10. Diagramme de séquence complet

```
Frontend            API Route          ComparePipeline      SearchPipeline     NextPlaid    LocalRegistry    LLM
   │                    │                     │                    │                │             │          │
   │ POST /compare/runs│                     │                    │                │             │          │
   │──────────────────→│                     │                    │                │             │          │
   │                    │  create_run(db)     │                    │                │             │          │
   │                    │────────────────────→│                    │                │             │          │
   │                    │                     │                    │                │             │          │
   │                    │  analyze(left,right)│                    │                │             │          │
   │                    │────────────────────→│                    │                │             │          │
   │                    │                     │  _discover_changes │                │             │          │
   │                    │                     │───────────────────→│                │             │          │
   │                    │                     │                    │  search(query) │             │          │
   │                    │                     │                    │───────────────→│             │          │
   │                    │                     │                    │←───────────────│             │          │
   │                    │                     │                    │  lexical_search│             │          │
   │                    │                     │                    │──────────────────────────────→│          │
   │                    │                     │                    │←──────────────────────────────│          │
   │                    │                     │                    │                │             │          │
   │                    │                     │  pair_evidence_rows│                │             │          │
   │                    │                     │───────────────────→│                │             │          │
   │                    │                     │                    │                │             │          │
   │                    │                     │  _decide_from_pairs│                │             │          │
   │                    │                     │───────────────────→│                │             │          │
   │                    │                     │                    │                │             │  analyze │
   │                    │                     │                    │────────────────────────────────────────→│
   │                    │                     │                    │←────────────────────────────────────────│
   │                    │                     │                    │                │             │          │
   │                    │  update_run(db)     │                    │                │             │          │
   │                    │←────────────────────│                    │                │             │          │
   │                    │                     │                    │                │             │          │
   │  GET /compare/runs/:id (polling)         │                    │                │             │          │
   │──────────────────→│                     │                    │                │             │          │
   │←──────────────────│  { result: {...} }  │                    │                │             │          │
```
