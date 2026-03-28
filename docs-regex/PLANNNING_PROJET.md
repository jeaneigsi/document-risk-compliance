# Plan de Développement - Projet Détection d'Incohérences Documentaires

## Résumé Exécutif

**Objectif** : Concevoir un pipeline capable de retrouver les preuves, détecter les incohérences entre documents longs, et transmettre au modèle seulement le contexte minimal nécessaire.

**Stack Technique** :
- Python 3.12 + uv
- FastAPI + Celery
- NextPlaid (Docker)
- LiteLLM + OpenRouter
- OpenTelemetry + Langfuse
- Cursor-like (Python pur)

---

# PARTIE I - MACRO PLANNING (Phases du Projet)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             TIMELINE PROJET                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1    ████████████████████  Infrastructure & Structure (Semaines 1-2) │
│                                                                              │
│  PHASE 2    ██████████████████████████████████████  Data Layer (Semaines 3-4) │
│                                                                              │
│  PHASE 3    ██████████████████████████████████████████████████  Search (Semaines 5-7) │
│                                                                              │
│  PHASE 4    ████████████████████████████████████████████████  Detection (Semaines 8-10) │
│                                                                              │
│  PHASE 5    ████████████████████████████████████  LLM Integration (Semaines 11-12) │
│                                                                              │
│  PHASE 6    ████████████████████████████████████████████  Monitoring (Semaines 13-14) │
│                                                                              │
│  PHASE 7    ████████████████████████████████████████████████████████████████  Évaluation (Semaines 15-18) │
│                                                                              │
│  PHASE 8    ████████████████████████████████████████████████████████████████  Expériences (Semaines 19-24) │
│                                                                              │
│  PHASE 9    ████████████████████████████████████  Rédaction (Semaines 25-28) │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## PHASE 1 - Infrastructure & Structure du Projet

**Durée** : 2 semaines

**Objectif** : Poser les fondations techniques solides

### Livrables
- Docker Compose fonctionnel (NextPlaid + Redis)
- Structure projet Python 3.12 avec uv
- Base de code FastAPI scaffolding
- Configuration environnementale

---

## PHASE 2 - Data Layer (Ingestion & Parsing)

**Durée** : 2 semaines

**Objectif** : Construire le pipeline d'ingestion documentaire

### Livrables
- Intégration OCR API
- Parser PDF (PyMuPDF)
- Normaliseur métadonnées
- Evidence Units construction
- Datasets téléchargés (FIND, Wikipedia Contradict, LongBench)

---

## PHASE 3 - Search Layer

**Durée** : 3 semaines

**Objectif** : Implémenter la double recherche (Cursor-like + NextPlaid)

### Livrables
- Index trigrammes + inversé (Python)
- Client HTTP NextPlaid
- Evidence retrieval
- Stratégies de ranking hybride

---

## PHASE 4 - Detection Layer

**Durée** : 3 semaines

**Objectif** : Détecter les incohérences avec cascade de comparateurs

### Livrables
- Détecteurs déterministes
- Comparateurs spécialisés
- Module de compression contexte
- Logique de décision

---

## PHASE 5 - LLM Integration

**Durée** : 2 semaines

**Objectif** : Intégrer LiteLLM + OpenRouter

### Livrables
- Client LiteLLM configuré
- Templates de prompts
- Gestion des coûts tokens
- Fallbacks

---

## PHASE 6 - Monitoring

**Durée** : 2 semaines

**Objectif** : Tracer tout le pipeline

### Livrables
- OpenTelemetry instrumentation
- Langfuse intégration


---

## PHASE 7 - Evaluation Framework

**Durée** : 4 semaines

**Objectif** : Construire le framework d'évaluation rigoureux

### Livrables
- Métriques recherche (Recall@k, MRR, nDCG)
- Métriques détection (Precision, Recall, F1)
- Métriques économiques (tokens, coût, latence)
- Baseline établie

---

## PHASE 8 - Expériences Scientifiques

**Durée** : 6 semaines

**Objectif** : Comparer les variantes et valider les hypothèses

### Livrables
- Résultats variantes (baseline, Cursor-like, NextPlaid, hybride)
- Analyse statistique
- Visualisations
- Validation hypothèses

---

## PHASE 9 - Rédaction

**Durée** : 4 semaines

**Objectif** : Synthétiser en mémoire/papier

### Livrables
- Chapitre État de l'art
- Chapitre Méthodologie
- Chapitre Résultats
- Chapitre Discussion

---

# PARTIE II - MICRO PLANNING (Tâches Détaillées)

## PHASE 1 - INFRASTRUCTURE & STRUCTURE

### Semaine 1 - Docker & Environment

#### Jour 1-2 : Docker Compose Setup
- [ ] Créer `docker-compose.yml`
  - Service NextPlaid (image `ghcr.io/lightonai/next-plaid:cpu-1.1.3`)
  - Service Redis (Celery broker)
  - Network `projet-1-network`
  - Volumes : `./storage/indices` pour NextPlaid
- [ ] Tester lancement `docker-compose up -d`
- [ ] Vérifier NextPlaid répond sur `http://localhost:8080`

#### Jour 3-4 : Projet Python avec uv
- [ ] Créer structure de base
  ```
  projet-1/
  ├── app/
  ├── workers/
  ├── storage/
  ├── tests/
  ├── pyproject.toml
  └── docker-compose.yml
  ```
- [ ] Initialiser `uv init` avec Python 3.12
- [ ] Définir dépendances core dans `pyproject.toml`
  - fastapi
  - uvicorn[standard]
  - celery
  - redis
  - httpx
  - pydantic
  - pydantic-settings
- [ ] Configurer `app/config.py` avec pydantic-settings
  - Variables environnement
  - NextPlaid URL
  - OCR API URL
  - OpenRouter API key

#### Jour 5 : FastAPI Scaffolding
- [ ] Créer `app/api/main.py`
  - Initialisation FastAPI
  - Middleware CORS
  - Route healthcheck
- [ ] Créer `app/api/routes.py` (squelette)
- [ ] Tester `uvicorn app.api.main:app --reload`

### Semaine 2 - Structure & Tests

#### Jour 1-3 : Arborescence complète
- [ ] Créer tous les modules avec `__init__.py`
  ```
  app/
  ├── api/
  ├── ingest/
  ├── search/
  ├── detect/
  ├── llm/
  ├── monitor/
  └── config.py
  ```
- [ ] Créer `workers/` avec `celery_app.py` et `tasks.py`
- [ ] Créer `tests/` avec `conftest.py`

#### Jour 4-5 : Tests Infrastructure
- [ ] Configurer pytest
- [ ] Test Docker Compose lancement
- [ ] Test FastAPI startup
- [ ] Test Celery connection Redis

---

## PHASE 2 - DATA LAYER

### Semaine 3 - Ingestion OCR & Parsing

#### Jour 1-3 : OCR API Client
- [ ] Créer `app/ingest/ocr.py`
  - Client HTTP pour OCR API
  - Gestion retries
  - Gestion erreurs
- [ ] Tests unitaires client OCR

#### Jour 4-5 : PDF Parser
- [ ] Créer `app/ingest/parser.py`
  - Intégration PyMuPDF
  - Extraction texte
  - Extraction métadonnées
  - Extraction tableaux (camelot-py)
- [ ] Tests sur PDF variés

### Semaine 4 - Datasets & Evidence Units

#### Jour 1-2 : Chargement Datasets
- [ ] Créer `app/ingest/datasets.py`
  - Fonction `load_find_dataset()`
  - Fonction `load_wikipedia_contradict()`
  - Fonction `load_longbench()`
- [ ] Télécharger échantillon FIND (100-200 docs)
- [ ] Script vérification structure

#### Jour 3-4 : Evidence Units
- [ ] Créer `app/search/evidence.py`
  - Classe `EvidenceUnit`
  - Mapping FIND → EvidenceUnit
  - Sérialisation/désérialisation
- [ ] Tests conversion FIND

#### Jour 5 : Normaliseur
- [ ] Créer `app/ingest/normalizer.py`
  - Extraction dates
  - Extraction montants
  - Extraction références
  - Validation métier

---

## PHASE 3 - SEARCH LAYER

### Semaine 5 - Cursor-like (Python)

#### Jour 1-3 : Index Trigrammes
- [ ] Créer `app/search/cursor_like.py`
  - Classe `TrigramIndex`
  - Construction index trigrammes
  - Posting lists
- [ ] Tests performance indexation

#### Jour 4-5 : Index Inversé
- [ ] Compléter `app/search/cursor_like.py`
  - Classe `InvertedIndex`
  - Tokenisation
  - Intersection posting lists
- [ ] Tests recherche

### Semaine 6 - NextPlaid Client

#### Jour 1-3 : Client HTTP
- [ ] Créer `app/search/nextplaid_client.py`
  - Connexion NextPlaid :8080
  - Indexation documents
  - Recherche sémantique
- [ ] Tests avec NextPlaid Docker

#### Jour 4-5 : Indexation Documents
- [ ] Pipeline indexation complète
  - EvidenceUnit → NextPlaid format
  - Batch indexing
  - Gestion erreurs

### Semaine 7 - Ranking Hybride

#### Jour 1-3 : Fusion Résultats
- [ ] Créer `app/search/ranking.py`
  - Fusion scores lexical + sémantique
  - Reranking top-k
  - Deduplication
- [ ] Tests fusion

#### Jour 4-5 : Métriques Recherche
- [ ] Implémenter Recall@k, MRR, nDCG
- [ ] Tests sur FIND gold evidences

---

## PHASE 4 - DETECTION LAYER

### Semaine 8 - Détecteurs Déterministes

#### Jour 1-3 : Détecteurs Base
- [ ] Créer `app/detect/deterministic.py`
  - `DateConflictDetector`
  - `AmountConflictDetector`
  - `ReferenceMismatchDetector`
- [ ] Tests unitaires

#### Jour 4-5 : Comparateurs Spécialisés
- [ ] Créer `app/detect/comparators.py`
  - `ClauseComparator`
  - `TableComparator`
  - `SectionComparator`

### Semaine 9 - Compression Contexte

#### Jour 1-3 : Minimal Context
- [ ] Créer `app/detect/compression.py`
  - `MinimalContextBundle`
  - Sélection preuves minimales
  - Règles métier
- [ ] Tests compression

#### Jour 4-5 : Décision
- [ ] Créer `app/detect/decision.py`
  - Logique de décision finale
  - Scoring gravité
  - Recommandation action

### Semaine 10 - Pipeline Detection

#### Jour 1-5 : Assemblage
- [ ] Créer `app/detect/pipeline.py`
  - Pipeline complet détection
  - Cascade de comparateurs
  - Routing vers LLM si nécessaire
- [ ] Tests end-to-end

---

## PHASE 5 - LLM INTEGRATION

### Semaine 11 - LiteLLM Setup

#### Jour 1-3 : Configuration
- [ ] Installer litellm
- [ ] Créer `app/llm/litellm_client.py`
  - Configuration OpenRouter
  - Modèles Haiku/Sonnet
  - Gestion API keys

#### Jour 4-5 : Prompts
- [ ] Créer `app/llm/prompts.py`
  - Template détection incohérence
  - Template explication
  - Template résumé

### Semaine 12 - Intégration Pipeline

#### Jour 1-5 : LLM dans Pipeline
- [ ] Intégration LLM dans `app/detect/pipeline.py`
- [ ] Gestion coûts tokens
- [ ] Fallbacks
- [ ] Tests end-to-end

---

## PHASE 6 - MONITORING

### Semaine 13 - OpenTelemetry

#### Jour 1-3 : Instrumentation
- [ ] Installer opentelemetry packages
- [ ] Créer `app/monitor/telemetry.py`
  - Spans pour chaque module
  - Métriques custom
- [ ] Intégration dans FastAPI

#### Jour 4-5 : Tempo/Jaeger
- [ ] Setup Tempo local
- [ ] Visualisation traces

### Semaine 14 - Langfuse

#### Jour 1-3 : Langfuse Setup
- [ ] Créer `app/monitor/langfuse.py`
  - Traces LLM
  - Datasets tracking
  - Runs expérimentaux


---

## PHASE 7 - EVALUATION FRAMEWORK

### Semaine 15-16 - Métriques

#### Jour 1-10 : Implémentation Métriques
- [ ] `app/eval/metrics.py`
  - Recall@k, MRR, nDCG (recherche)
  - Precision, Recall, F1 (détection)
  - Token count, cost, latency (économie)
- [ ] Tests validation métriques

### Semaine 17-18 - Baseline

#### Jour 1-10 : Établir Baseline
- [ ] Pipeline baseline (sans Cursor-like/NextPlaid)
- [ ] Résultats sur FIND échantillon
- [ ] Documentation baseline

---

## PHASE 8 - EXPÉRIENCES SCIENTIFIQUES

### Semaine 19-20 : Variantes Recherche

#### Jour 1-10 : Comparaison Stratégies
- [ ] Baseline lexicale simple
- [ ] Cursor-like seul
- [ ] NextPlaid seul
- [ ] Hybride Cursor-like + NextPlaid

### Semaine 21-22 : Expériences Compression

#### Jour 1-10 : LongBench
- [ ] Expériences compression contexte
- [ ] Mesure compression_ratio vs qualité

### Semaine 23-24 : Analyse Résultats

#### Jour 1-10 : Synthèse
- [ ] Analyse statistique
- [ ] Visualisations
- [ ] Validation hypothèses

---

## PHASE 9 - RÉDACTION

### Semaine 25-26 : État de l'art & Méthodologie

#### Jour 1-10 : Rédaction
- [ ] Chapitre 1 : Introduction
- [ ] Chapitre 2 : État de l'art
- [ ] Chapitre 3 : Méthodologie

### Semaine 27-28 : Résultats & Discussion

#### Jour 1-10 : Rédaction
- [ ] Chapitre 4 : Résultats
- [ ] Chapitre 5 : Discussion
- [ ] Conclusion & Perspectives

---

# PARTIE III - DÉPENDANCES ENTRE TÂCHES

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           GRAPH OF DEPENDENCIES                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [Docker Setup] ──▶ [Projet Python] ──▶ [FastAPI Scaffold]                │
│                           │                                                 │
│                           ▼                                                 │
│                    [Data Layer]                                            │
│                           │                                                 │
│         ┌─────────────────┼─────────────────┐                              │
│         ▼                 ▼                 ▼                              │
│  [Cursor-like]    [NextPlaid Client]  [Datasets]                          │
│         │                 │                 │                              │
│         └─────────────────┴─────────────────┘                              │
│                           │                                                 │
│                           ▼                                                 │
│                    [Ranking Hybride]                                        │
│                           │                                                 │
│                           ▼                                                 │
│                    [Detection Layer]                                       │
│                           │                                                 │
│                           ▼                                                 │
│                    [LLM Integration]                                       │
│                           │                                                 │
│                           ▼                                                 │
│                    [Monitoring]                                             │
│                           │                                                 │
│                           ▼                                                 │
│                    [Evaluation]                                             │
│                           │                                                 │
│                           ▼                                                 │
│                    [Expériences]                                           │
│                           │                                                 │
│                           ▼                                                 │
│                    [Rédaction]                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

# PARTIE IV - RISQUES & MITIGATIONS

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| NextPlaid ne répond pas aux attentes | Moyenne | Élevé | Avoir alternative ColBERT |
| FIND dataset inaccessible | Faible | Élevé | Avoir datasets de secours |
| Coûts LLM explosent | Moyenne | Moyen | Compression agressive, fallback local |
| Performance Cursor-like insuffisante | Moyenne | Moyen | Optimisations, Rust si nécessaire |
| Délais glissants | Moyenne | Moyen | Priorisation stricte, MVP plus petit |

---

# PARTIE V - CRITÈRES DE SUCCÈS

## Techniques
- [ ] NextPlaid fonctionnel en Docker
- [ ] Cursor-like indexe 10k docs en < 30s
- [ ] FIND recall@5 > 80%
- [ ] Compression ratio > 70%
- [ ] Latence pipeline < 10s

## Scientifiques
- [ ] Hypothèse 1 validée : Cursor-like réduit espace candidat
- [ ] Hypothèse 2 validée : NextPlaid améliore rappel reformulations
- [ ] Hypothèse 3 validée : Hybride > chacune isolée
- [ ] Hypothèse 4 validée : Contexte minimal conserve qualité

## Académiques
- [ ] Baseline solide établie
- [ ] Résultats reproductibles
- [ ] Mémoire/méthodologie claire
- [ ] Contribution évidente

---

*Document créé le 24 mars 2026*
*Version 1.0*
