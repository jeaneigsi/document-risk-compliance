# Strategie de Recherche Semantique — Documentation Complete

## Vue d'ensemble

La strategie **semantique** (`strategy="semantic"`) s'appuie sur **NextPlaid**, un service externe de recherche a interaction tardive (*late-interaction model*), pour retrouver des unites de preuve (*evidence units*) pertinentes en s'appuyant sur des **embeddings vectoriels** et le modele **ColBERT**.

Contrairement a la recherche lexicale (trigrammes + index inverse), la recherche semantique comprend le **sens** des requetes : les synonymes, les reformulations et les concepts abstraits sont correctement associes. En revanche, elle necessite un service externe (NextPlaid), un modele d'embedding et un reseau fiable.

Le client NextPlaid est implemente dans `app/search/nextplaid_client.py` et orchestre la creation d'index, l'indexation de documents, la recherche semantique et la suppression de documents via une API HTTP REST asynchrone (httpx).

---

## Architecture des composants

```
Ingestion (workers/tasks.py)
  │
  ├── OCR → build_evidence_units_from_ocr()
  │         │
  │         └── EvidenceUnit[] (content, metadata, page_number, source_type)
  │
  └── SearchPipeline.index_evidence_units()
        │
        ├── LocalSearchRegistry.add_evidence_units()     [index lexicale locale]
        │
        └── NextPlaidClient.index_evidence_units()
              │
              ├── create_index(index_name, nbits=4)
              │     └── POST /indices  {name, config: {nbits}}
              │
              └── add(index_name, documents, metadata)
                    └── POST /indices/{name}/update_with_encoding
                          {documents: [...], metadata: [...]}

Recherche (pipeline.py)
  │
  ├── SearchPipeline.run(strategy="semantic")
  │     │
  │     ├── NextPlaidClient.search(query, index_name, top_k)
  │     │     │
  │     │     └── POST /indices/{name}/search_with_encoding
  │     │           {queries: [query], params: {top_k, filters...}}
  │     │
  │     ├── _parse_search_results()  →  [{id, score, metadata}, ...]
  │     │
  │     └── rank_search_results()    →  tri par score desc, top_k
  │
  └── Monitoring
        ├── start_span("search.pipeline.run")    [OpenTelemetry]
        └── tracker.trace() + tracker.event()    [Langfuse]
```

**Fichiers sources :**

| Fichier | Role |
|---------|------|
| `app/search/nextplaid_client.py` | Client HTTP asynchrone pour NextPlaid |
| `app/search/pipeline.py` | Orchestration de la pipeline de recherche |
| `app/search/ranking.py` | Classement et fusion des resultats |
| `app/search/evidence.py` | Modele EvidenceUnit et construction depuis OCR |
| `app/search/local_registry.py` | Registre des indexes lexicaux en memoire |
| `app/config.py` | Configuration NextPlaid et monitoring |
| `app/monitor/telemetry.py` | OpenTelemetry spans avec fallback no-op |
| `app/monitor/langfuse.py` | Tracing Langfuse avec fallback securise |
| `workers/tasks.py` | Taches Celery d'ingestion et de recherche |

---

## 1. Le client NextPlaid en detail

### Principe

**NextPlaid** est un serveur de recherche semantique qui implemente le modele **ColBERT** (Contextual Late Interaction over BERT). Contrairement aux modeles bi-encodeurs classiques qui produisent un vecteur unique par document, ColBERT produit une **representation par token** et calcule un score de similarite fine (*MaxSim*) entre la requete et chaque document.

Le client `NextPlaidClient` communique avec NextPlaid via une API REST HTTP en utilisant **httpx** en mode asynchrone. L'encodage est realise **cote serveur** : le client envoie du texte brut et NextPlaid gere les embeddings internement.

### Initialisation et configuration

```python
class NextPlaidClient:
    def __init__(self, base_url=None, timeout=None):
        settings = get_settings()
        self.base_url = (base_url or settings.next_plaid_url).rstrip("/")
        self.timeout = timeout or settings.next_plaid_timeout
        self._known_indices: set[str] = set()
```

**Parametres de configuration** (depuis `app/config.py` et `.env`) :

| Parametre | Variable d'env | Defaut | Description |
|-----------|---------------|--------|-------------|
| `next_plaid_url` | `NEXT_PLAID_URL` | `http://localhost:8081` | URL de base du serveur NextPlaid |
| `next_plaid_timeout` | `NEXT_PLAID_TIMEOUT` | `30` | Timeout HTTP en secondes |
| `embedding_model` | `EMBEDDING_MODEL` | `openrouter/qwen/qwen3-embedding-4b` | Modele d'embedding (configurable) |
| `embedding_dimensions` | `EMBEDDING_DIMENSIONS` | `None` | Dimensions des embeddings (auto si None) |
| `search_auto_index` | `SEARCH_AUTO_INDEX` | `True` | Indexation automatique a l'ingestion |
| `search_default_index` | `SEARCH_DEFAULT_INDEX` | `default` | Nom de l'index par defaut |

Le cache `_known_indices` evite les appels `create_index` redondants pour les index deja crees au cours de la session.

### Health check

```python
async def health_check(self) -> bool:
    try:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/health")
            return response.status_code == 200
    except Exception:
        return False
```

Verifie la disponibilite de NextPlaid via `GET /health`. Retourne `False` en cas d'indisponibilite (pas de levée d'exception).

### Gestion du cycle de vie des index

#### Creation d'index

```python
async def create_index(self, index_name: str, nbits: int = 4) -> dict:
```

- Endpoint : `POST /indices`
- Payload : `{"name": index_name, "config": {"nbits": nbits}}`
- Parametre `nbits` : nombre de bits pour la quantification des embeddings (defaut 4). Une valeur plus basse = compression plus forte = recherche plus rapide mais moins precise.
- Gere les codes de retour : `200` (OK), `201` (cree), `409` (existe deja) sont consideres comme des succes.
- **Fallback** : si le format principal retourne 404, un schema alternatif sans `config` est essaye : `{"name": index_name, "nbits": nbits}`.
- Met en cache le nom d'index dans `_known_indices` pour eviter les creations ulterieures.

#### Ajout de documents

```python
async def add(self, index_name: str, documents: list[str],
              metadata: list[dict] | None = None) -> dict:
```

- Endpoint principal : `POST /indices/{index_name}/update_with_encoding`
- Payload : `{"documents": [...], "metadata": [...]}`
- L'encodage est realise **cote serveur** (NextPlaid gere les embeddings ColBERT).
- **Fallback legacy** : si 404, essai de `POST /indexes/{index_name}/documents` avec un format de document etendu incluant `id`, `text` et `metadata`.

#### Suppression de documents

```python
async def delete(self, index_name: str, filter_condition: str,
                 filter_parameters: list | None = None) -> dict:
```

- Endpoint principal : `POST /indices/{index_name}/delete`
- Payload : `{"filter_condition": "...", "filter_parameters": [...]}`
- **Fallback** : si 404, essai de `POST /indices/{index_name}/delete_by_predicate`

---

## 2. Recherche semantique — Flux complet

### Endpoint de recherche

```python
async def search(self, query: str, index_name: str = "default",
                 top_k: int = 10, filters: dict | None = None,
                 filter_condition: str | None = None,
                 filter_parameters: list | None = None) -> list[dict]:
```

#### Parametres de recherche

| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `query` | `str` | (requis) | Texte de la requete |
| `index_name` | `str` | `"default"` | Nom de l'index NextPlaid |
| `top_k` | `int` | `10` | Nombre maximum de resultats |
| `filters` | `dict` | `None` | Filtres metadata (paires cle-valeur) |
| `filter_condition` | `str` | `None` | Condition de filtrage avancee |
| `filter_parameters` | `list` | `None` | Parametres de la condition de filtrage |

#### Appel API principal

- Endpoint : `POST /indices/{index_name}/search_with_encoding`
- Payload :

```json
{
  "queries": ["texte de la requete"],
  "params": {
    "top_k": 10,
    "filters": {"document_id": "doc_123"},
    "filter_condition": "...",
    "filter_parameters": [...]
  }
}
```

L'encodage de la requete est realise **cote serveur** par NextPlaid, qui :
1. Encode la requete en representations ColBERT (un vecteur par token)
2. Compare avec les representations indexees via MaxSim
3. Retourne les `top_k` resultats les plus pertinents avec leurs scores

#### Fallback legacy

Si l'endpoint principal retourne 404, le client essaie l'ancien format :

- Endpoint : `POST /indexes/{index_name}/search`
- Payload : `{"query": query, "top_k": top_k, "filters": {...}}`
- Si ce second endpoint retourne aussi 404, une liste vide est retournee (pas d'erreur).

### Parsing des resultats — `_parse_search_results`

La methode statique `_parse_search_results` gere **quatre formats de reponse** possibles pour assurer la compatibilite avec differentes versions de l'API NextPlaid :

```python
@staticmethod
def _parse_search_results(data: Any) -> list[dict[str, Any]]:
```

| Format detecte | Structure | Transformation |
|----------------|-----------|----------------|
| Liste directe | `[{"id": ..., "score": ...}]` | Retour tel quel |
| Cle `"results"` avec `"document_ids"` | `{"results": [{"document_ids": [...], "scores": [...], "metadata": [...]}]}` | Decompression en liste de dict individuels |
| Cle `"results"` simple | `{"results": [...]}` | Extraction de la sous-liste |
| Cle `"data"` | `{"data": [...]}` | Extraction de la sous-liste |

Pour le format `document_ids`, chaque resultat est reconstruit :

```python
{
    "id": meta.get("id") or meta.get("document_id") or doc_id,
    "score": float(scores[i]),
    "metadata": meta if isinstance(meta, dict) else {}
}
```

**Priorite d'identification** : `metadata.id` > `metadata.document_id` > `document_id` brut.

---

## 3. Flux d'indexation semantique

### Etape 1 — Extraction OCR et construction des EvidenceUnits

Dans `workers/tasks.py`, lors du traitement d'ingestion :

```python
evidence_units = build_evidence_units_from_ocr(
    document_id=document_id,
    filename=filename,
    md_results=md_results,
    layout_details=layout_details,
)
```

La fonction `build_evidence_units_from_ocr` (dans `evidence.py`) parcourt les elements de layout extraits par OCR et cree des `EvidenceUnit` :

```python
class EvidenceUnit(BaseModel):
    evidence_id: str           # "doc_id:p{page}:e{elem}"
    document_id: str           # Document source
    content: str               # Texte a indexer
    source_type: str           # "layout", "markdown_block", "markdown"
    page_number: int | None    # Numero de page
    metadata: dict             # filename, layout_index, etc.
```

**Sources de contenu indexees** :
1. **Elements de layout** — Chaque element detecte par OCR (paragraphes, titres, tableaux) avec son label comme `source_type`
2. **Blocs markdown** — Paragraphes du markdown complet (apres split par double saut de ligne), uniquement s'ils ne sont pas deja presents dans les elements de layout (deduplication par contenu normalise)
3. **Markdown complet** — Fallback si aucun element de layout n'a ete extrait

**Deduplication** : Le contenu est normalise (espaces collapses, minuscule) et compare avant indexation pour eviter les doublons entre layout et markdown.

### Etape 2 — Indexation dans la pipeline

```python
# pipeline.py
async def index_evidence_units(self, evidence_units, index_name="default"):
    # 1. Indexation lexicale locale (simultanee)
    local_count = self.registry.add_evidence_units(index_name, evidence_units)

    # 2. Indexation semantique dans NextPlaid
    response = await self.client.index_evidence_units(
        evidence_units=evidence_units,
        index_name=index_name,
    )
```

L'indexation est **duale** : chaque unite est indexee a la fois dans l'index lexical local (trigrammes + inversé) et dans NextPlaid (embeddings ColBERT).

### Etape 3 — Indexation dans NextPlaid

```python
# nextplaid_client.py
async def index_evidence_units(self, evidence_units, index_name="default", nbits=4):
    documents = [unit.content for unit in evidence_units]
    metadata = [
        {
            "id": unit.evidence_id,
            "document_id": unit.document_id,
            "source_type": unit.source_type,
            "page_number": unit.page_number,
            **unit.metadata,
        }
        for unit in evidence_units
    ]
    await self.create_index(index_name=index_name, nbits=nbits)
    return await self.add(index_name=index_name, documents=documents, metadata=metadata)
```

**Metadata indexees par evidence unit** :

| Champ | Source | Description |
|-------|--------|-------------|
| `id` | `evidence_id` | Identifiant unique de l'unite |
| `document_id` | `document_id` | Document parent |
| `source_type` | `source_type` | Type d'extraction (layout, markdown_block, etc.) |
| `page_number` | `page_number` | Page dans le document source |
| `filename` | `metadata.filename` | Nom du fichier original |
| `layout_index` | `metadata.layout_index` | Index de l'element dans le layout OCR |

---

## 4. Flux de recherche semantique

### Etape 1 — Reception et routage

```python
# pipeline.py
async def run(self, query, index_name="default", top_k=10, strategy="semantic"):
    if strategy in ("semantic", "hybrid"):
        semantic_results = await self.client.search(
            query=query,
            index_name=index_name,
            top_k=top_k,  # top_k brut en mode semantic
        )
        semantic_results = rank_search_results(semantic_results, top_k=top_k)
```

En mode `semantic` pur, le `top_k` est passe directement au client NextPlaid. En mode `hybrid`, un `top_k` interne elargi est utilise (`max(top_k, min(50, top_k * 3))`) pour avoir plus de candidats avant fusion.

### Etape 2 — Appel NextPlaid

Le client envoie la requete a `POST /indices/{index_name}/search_with_encoding`. NextPlaid :
1. Encode la requete en representations ColBERT
2. Calcule les scores MaxSim contre tous les documents indexes
3. Retourne les resultats tries par score de similarite

### Etape 3 — Parsing et classement

```python
# ranking.py
def rank_search_results(semantic_results, top_k=10):
    sorted_results = sorted(
        semantic_results,
        key=lambda item: float(item.get("score", 0.0)),
        reverse=True,
    )
    return sorted_results[:top_k]
```

Classement simple par score decroissant. Les scores sont les scores de similarite ColBERT bruts retournes par NextPlaid.

### Etape 4 — Gestion des erreurs

```python
# pipeline.py
try:
    semantic_results = await self.client.search(...)
except Exception as exc:
    semantic_error = str(exc)
    semantic_results = []
    semantic_candidate_count = 0
    logger.warning("semantic search failed index=%s strategy=%s query_len=%s error=%s",
                   index_name, strategy, len(query), exc)
```

En cas d'echec de la recherche semantique :
- Les resultats semantiques sont vides (`[]`)
- L'erreur est enregistree dans `semantic_error` et incluse dans la reponse
- Un warning est logged
- En mode `hybrid`, la fusion se poursuit avec uniquement les resultats lexicaux (degradation gracieuse)

---

## 5. Scoring et ranking

### Score semantique pur

En strategie `semantic`, le score est directement le **score ColBERT** retourne par NextPlaid. Il s'agit d'un score de similarite a interaction tardive (*late-interaction score*) calcule par l'operateur MaxSim :

```
score_colbert = sum_j  max_i  (Q_j . D_i)
```

Ou `Q_j` sont les representations de la requete et `D_i` celles du document. Ce score capture les correspondances les plus fines token-par-token entre requete et document.

### Fusion hybride — `fuse_search_results`

En strategie `hybrid`, les resultats semantiques et lexicaux sont fusionnes :

```python
def fuse_search_results(semantic_results, lexical_results, top_k=10,
                       semantic_weight=0.7, lexical_weight=0.3):
```

**Algorithme** :

1. **Normalisation min-max** des scores de chaque source independamment
2. **Composant fusionne** par entree :

```
fused_component = 0.65 * normalized_score + 0.35 * (1 / (rank_denominator + rank))
final_score += fused_component * weight
```

Ou :
- `rank_denominator = max(60, top_k * 6)` — amortit l'impact du rang
- Le score normalise compte pour 65% du signal
- Le rang compte pour 35% du signal

3. **Poids par defaut** : semantique = 70%, lexical = 30%
4. **Deduplication** par ID — les memes documents trouves par les deux strategies sont fusionnes en cumulant leurs scores ponderes
5. **Tri final** par score fusionne decroissant, troncature a `top_k`

**Resultat fusionne** :

```python
{
    "id": item_id,
    "score": 0.0,             # score fusionne final
    "semantic_score": 0.0,    # meilleur score semantique brut
    "lexical_score": 0.0,     # meilleur score lexical brut
    "semantic_rank": None,    # rang dans les resultats semantiques
    "lexical_rank": None,     # rang dans les resultats lexicaux
    "sources": ["semantic", "lexical"],  # sources ayant trouve ce document
    "metadata": {...},
    "text": "...",
}
```

---

## 6. Monitoring et observabilite

### OpenTelemetry — Spans

Le module `app/monitor/telemetry.py` fournit un wrapper autour d'OpenTelemetry avec un **fallback no-op** lorsque le monitoring est desactive ou lorsque la librairie n'est pas installee.

```python
@contextmanager
def start_span(name: str, attributes: dict | None = None):
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            span.set_attribute(key, value)
        yield span
```

**Spans utilises dans la recherche semantique** :

| Span | Attributes | Declencheur |
|------|-----------|-------------|
| `search.pipeline.run` | `index_name`, `strategy`, `top_k` | Debut de `SearchPipeline.run()` |
| `search.pipeline.index` | `index_name`, `items` | Debut de `index_evidence_units()` |

### Langfuse — Traces et evenements

Le module `app/monitor/langfuse.py` fournit un wrapper autour du SDK Langfuse avec un **fallback securise** (singleton, desactive si clefs absentes).

**Configuration** :

| Parametre | Variable d'env | Defaut |
|-----------|---------------|--------|
| `monitoring_enabled` | `MONITORING_ENABLED` | `True` |
| `langfuse_host` | `LANGFUSE_HOST` | `https://cloud.langfuse.com` |
| `langfuse_public_key` | `LANGFUSE_PUBLIC_KEY` | `""` |
| `langfuse_secret_key` | `LANGFUSE_SECRET_KEY` | `""` |
| `otel_service_name` | `OTEL_SERVICE_NAME` | `docs-regex-backend` |

**Traces emises par la recherche semantique** :

```python
# Trace de recherche
trace_id = tracker.trace(
    name="search.run",
    input_payload={"query": query, "index_name": index_name, "strategy": strategy},
    metadata={
        "top_k": top_k,
        "latency_ms": latency_ms,
        "candidate_count": candidate_count,
        "candidate_kept_count": candidate_kept_count,
        "semantic_top_k_internal": semantic_top_k_internal,
    },
)
tracker.event(
    trace_id=trace_id,
    name="search.results",
    output={"count": len(ranked_results)},
    metadata={
        "strategy": strategy,
        "latency_ms": latency_ms,
        "candidate_count": candidate_count,
        "candidate_kept_count": candidate_kept_count,
    },
)
```

**Metriques collectees** :

| Metrique | Description |
|----------|-------------|
| `latency_ms` | Latence totale de la recherche en ms |
| `candidate_count` | Nombre total de candidats avant classement |
| `candidate_kept_count` | Nombre de resultats apres classement et troncature |
| `semantic_error` | Message d'erreur si echec semantique (ou None) |
| `semantic_top_k_internal` | top_k interne elargi (mode hybrid uniquement) |

**Trace d'indexation** :

```python
trace_id = tracker.trace(
    name="search.index",
    input_payload={"index_name": index_name, "items": len(evidence_units)},
    metadata={"local_indexed_count": local_count},
)
tracker.event(trace_id=trace_id, name="search.indexed", output=response)
```

---

## 7. Comparaison avec les autres strategies

| Critere | Semantique | Lexical | Hybrid | RG (regex) |
|---------|-----------|---------|--------|------------|
| Service externe | NextPlaid | Non | NextPlaid | Non |
| GPU requis | Oui (serveur) | Non | Oui (serveur) | Non |
| Temps de response | ~50-200 ms | ~1-5 ms | ~50-200 ms | ~1-10 ms |
| Fautes de frappe | Oui | Partiel (trigrammes) | Oui | Non |
| Synonymes | Oui | Non | Oui | Non |
| Reformulations | Oui | Non | Oui | Non |
| Regex | Non | Via planificateur | Via planificateur | Natif |
| Deterministe | Non | Oui | Non | Oui |
| Cout LLM | 0 | 0 | 0 | 0 |
| Cout d'indexation | Serveur ColBERT | Memoire | Les deux | Memoire |
| Persistance | NextPlaid gere | Memoire uniquement | NextPlaid + memoire | Memoire uniquement |
| Fallback si indisponible | Liste vide | N/A | Resultats lexicaux seuls | N/A |
| Modele d'embedding | ColBERT (serveur) | N/A | ColBERT + trigrammes | N/A |

---

## 8. Points forts et limites

### Points forts

- **Comprehension semantique** — Capture les synonymes, reformulations et concepts abstraits que le lexical ne peut pas detecter. "Vehicule" et "automobile" sont correctement associes.
- **Modele ColBERT** — L'interaction tardive offre une precision superieure aux bi-encodeurs classiques (type DPR) car elle compare token-par-token plutot que vecteur-contre-vecteur.
- **Encodage serveur** — Le client n'a pas besoin de GPU ni de modele d'embedding local. Tout le traitement lourd est delegue a NextPlaid.
- **Filtrage avance** — Support de filtres metadata, conditions de filtrage et parametres pour affiner les resultats de recherche.
- **Compatibilite retrograde** — Fallback automatique vers les anciens endpoints API NextPlaid si les nouveaux ne sont pas disponibles (404).
- **Degradation gracieuse** — En mode hybrid, si NextPlaid est indisponible, les resultats lexicaux sont utilises seuls. La recherche echoue silencieusement plutot que de planter.
- **Dual-indexation** — Chaque document est indexe a la fois dans NextPlaid et dans l'index lexical local, permettant les recherches dans toutes les strategies.

### Limites

- **Dependance reseau** — Le serveur NextPlaid doit etre accessible. Une indisponibilite arrete completement la recherche semantique pure.
- **Latence** — 10x a 100x plus lent que la recherche lexicale locale (50-200 ms vs 1-5 ms) en raison de l'encodage et du calcul de similarite.
- **Cout d'infrastructure** — Necessite un serveur NextPlaid avec GPU pour l'encodage ColBERT.
- **Non-deterministe** — Les scores peuvent varier legerement selon l'etat interne de NextPlaid (quantification, ordre d'indexation).
- **Pas de recherche par motifs** — Contrairement au mode RG (regex), impossible de chercher des motifs comme `article.*3[0-9]+`.
- **Index en memoire locale** — La partie lexicale de la dual-indexation est perdue au redemarrage du backend (seul NextPlaid persiste).
- **Taille des documents** — Les evidence units tres longues peuvent etre tronquees ou mal representees par ColBERT (limite de tokens du modele).
