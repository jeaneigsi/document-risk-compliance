# Strategie de Recherche Hybride -- Documentation Complete

## Vue d'ensemble

La strategie **hybride** (`strategy="hybrid"`) est le mode de recherche par defaut du systeme. Elle combine deux sources de retrieval complementaires :

1. **La recherche semantique** via NextPlaid (embeddings + similarite cosinus), qui comprend le sens des requetes et capture les synonymes, paraphrases et concepts proches.
2. **La recherche lexicale** via un index local en memoire (trigrammes + index inverse), qui excelle sur les correspondances exactes, les termes techniques, les numeros d'articles et les codes specifiques.

Le principe fondamental est la **fusion par score normalise + signal de rang** avec une ponderation 70/30 en faveur du semantique. Les deux recherches sont lancees en parallele conceptuelle (l'une asynchrone, l'autre synchrone), puis leurs resultats sont fusionnes et dedupliques via `fuse_search_results()`.

Contrairement aux strategies pures (`semantic` ou `lexical`), le mode hybride :
- **Elargit le pool de candidats semantiques** en demandant `top_k * 3` resultats (plafonne a 50) a NextPlaid, pour maximiser les chances de trouver des documents pertinents avant la fusion.
- **Grace a la deduplication**, un document trouve par les deux sources cumule les signaux des deux et voit son score augmente.
- **Degradation gracieuse** : si le service semantique echoue, le systeme retombe sur les resultats lexicaux seuls.

---

## Architecture des composants

```
SearchPipeline.run(strategy="hybrid")
  |
  +-- Etape 1 : Calcul du semantic_top_k_internal
  |     semantic_top_k_internal = max(top_k, min(50, top_k * 3))
  |
  +-- Etape 2 : Recherche semantique (async)
  |     |
  |     +-- NextPlaidClient.search(query, top_k=semantic_top_k_internal)
  |     +-- rank_search_results(semantic_results, top_k=semantic_top_k_internal)
  |     +-- [En cas d'echec] semantic_results = [], semantic_error capture
  |
  +-- Etape 3 : Recherche lexicale (sync)
  |     |
  |     +-- LocalSearchRegistry.lexical_search(query, top_k)
  |           |
  |           +-- TrigramIndex      (55% du score lexical)
  |           +-- InvertedIndex     (35% du score lexical)
  |           +-- Phrase Bonus      (10% du score lexical)
  |
  +-- Etape 4 : Fusion
  |     |
  |     +-- fuse_search_results(semantic_results, lexical_results, top_k)
  |           |
  |           +-- Normalisation min-max des scores (chaque source)
  |           +-- Fusion score + rang par document (70% sem / 30% lex)
  |           +-- Deduplication par ID de document
  |           +-- Tri par score fusionne decroissant
  |           +-- Retour des top_k premiers
  |
  +-- Etape 5 : Telemetrie et retour
        |
        +-- Langfuse trace (latence, comptes, semantic_error)
        +-- Retour du dict de resultats
```

**Fichiers sources :**

| Fichier | Role |
|---------|------|
| `app/search/pipeline.py` | Orchestration de la pipeline, appel des deux sources |
| `app/search/ranking.py` | Fonctions de tri et de fusion (`rank_search_results`, `fuse_search_results`) |
| `app/search/nextplaid_client.py` | Client asynchrone pour le service semantique NextPlaid |
| `app/search/local_registry.py` | Registre des indexes lexicaux en memoire |
| `app/search/evidence.py` | Modele `EvidenceUnit` (unites de preuve indexees) |
| `app/eval/runner.py` | Evaluation multi-strategies, incluant hybrid |

---

## 1. Elargissement du pool semantique -- `semantic_top_k_internal`

### Pourquoi elargir ?

En mode hybride, la recherche semantique demande **plus de resultats** que le `top_k` final demande par l'utilisateur. Cela augmente la probabilite qu'un document pertinent soit dans le pool semantique avant la fusion avec le lexical.

### Formule

```python
semantic_top_k_internal = max(top_k, min(50, top_k * 3))
```

Soit, en detaillant :
1. `top_k * 3` : on multiplie par 3 le nombre de resultats demandes
2. `min(50, ...)` : on plafonne a 50 pour ne pas surcharger le service semantique
3. `max(top_k, ...)` : on garantit au minimum le `top_k` demande

### Tableau de correspondance

| `top_k` demande | `top_k * 3` | Plafond 50 | `semantic_top_k_internal` |
|:---------------:|:-----------:|:----------:|:------------------------:|
| 5               | 15          | 15         | **15**                   |
| 10              | 30          | 30         | **30**                   |
| 15              | 45          | 45         | **45**                   |
| 17              | 51          | 50         | **50**                   |
| 20              | 60          | 50         | **50**                   |
| 50              | 150         | 50         | **50**                   |
| 100             | 300         | 50         | **100** (max(top_k, 50)) |

L'elargissement ne s'applique qu'en mode `hybrid`. En mode `semantic` pur, le `top_k` original est utilise tel quel.

---

## 2. Recherche semantique -- Appel NextPlaid

### Sequence

```python
# pipeline.py, lignes 52-74
if strategy in ("semantic", "hybrid"):
    try:
        semantic_results = await self.client.search(
            query=query,
            index_name=index_name,
            top_k=semantic_top_k_internal,  # elargi en hybrid
        )
        semantic_candidate_count = len(semantic_results)
        semantic_results = rank_search_results(
            semantic_results,
            top_k=semantic_top_k_internal,  # trie et tronque
        )
    except Exception as exc:
        semantic_error = str(exc)
        semantic_results = []
        semantic_candidate_count = 0
        logger.warning(
            "semantic search failed index=%s strategy=%s query_len=%s error=%s",
            index_name, strategy, len(query), exc,
        )
```

### Points cles

- L'appel est **asynchrone** (`await`), ce qui signifie qu'il pourrait etre parallellise avec le lexical a l'avenir.
- Les resultats sont tries par score decroissant via `rank_search_results()`, qui est un simple tri + troncature.
- L'erreur est **capturee et journalisee**, mais ne provoque **pas** d'arret de la pipeline. Le systeme continue avec les resultats lexicaux uniquement.

### Format des resultats semantiques

Chaque element de `semantic_results` est un dictionnaire contenant au minimum :
```python
{
    "id": "doc_id:e_idx:s_idx",    # identifiant de l'unite de preuve
    "score": 0.87,                  # score de similarite cosinus (NextPlaid)
    "text": "...",                  # texte du fragment
    "metadata": {...},              # metadonnees (filename, page, etc.)
}
```

---

## 3. Recherche lexicale -- Index local

### Sequence

```python
# pipeline.py, lignes 76-82
if strategy in ("lexical", "hybrid"):
    lexical_results = self.registry.lexical_search(
        index_name=index_name,
        query=query,
        top_k=top_k,  # pas d'elargissement pour le lexical
    )
    lexical_candidate_count = len(lexical_results)
```

### Points cles

- L'appel est **synchrone** et **local** (pas de reseau).
- Le `top_k` demande est le `top_k` original de l'utilisateur (pas d'elargissement).
- Le score lexical est un composite : `0.55 * trigram_overlap + 0.35 * token_match + 0.10 * phrase_bonus` (voir documentation lexicale pour les details).

---

## 4. Algorithme de fusion -- `fuse_search_results`

### Signature

```python
# ranking.py, lignes 27-33
def fuse_search_results(
    semantic_results: list[dict[str, Any]],
    lexical_results: list[dict[str, Any]],
    top_k: int = 10,
    semantic_weight: float = 0.7,
    lexical_weight: float = 0.3,
) -> list[dict[str, Any]]:
```

### Parametres

| Parametre | Defaut | Description |
|-----------|--------|-------------|
| `semantic_results` | -- | Resultats tries de NextPlaid (elargis en hybrid) |
| `lexical_results` | -- | Resultats de l'index local |
| `top_k` | 10 | Nombre de resultats finaux a retourner |
| `semantic_weight` | 0.7 | Poids du signal semantique dans la fusion |
| `lexical_weight` | 0.3 | Poids du signal lexical dans la fusion |

### Etape 4.1 -- Normalisation min-max

Les scores des deux sources vivent dans des echelles differentes (le semantique peut etre entre 0.5 et 0.99, le lexical entre 0.0 et 1.0). Avant la fusion, chaque source est normalisee independamment :

```python
# ranking.py, lignes 39-55
def normalize_scores(items):
    scores_by_id = {
        _ensure_id(item): float(item.get("score", 0.0))
        for item in items
        if _ensure_id(item)
    }
    if not scores_by_id:
        return {}
    min_score = min(score_values)
    max_score = max(score_values)
    if max_score <= min_score:
        return {id: 1.0 for id in scores_by_id}  # cas degeneré
    return {
        id: (score - min_score) / (max_score - min_score)
        for id, score in scores_by_id.items()
    }
```

**Formule de normalisation :**

```
score_norm = (score - min) / (max - min)
```

Plage resultante : **[0.0, 1.0]** pour chaque source, ou 1.0 = meilleur resultat de la source.

**Cas degeneres :**
- Si la liste est vide : dictionnaire vide `{}` (les scores manquants seront traites comme 0.0).
- Si tous les scores sont identiques (`max <= min`) : tous les scores normalises sont a `1.0`.

### Etape 4.2 -- Fusion score + rang

Pour chaque resultat de chaque source, on calcule un **composant fusionne** qui combine le score normalise et le rang :

```python
# ranking.py, lignes 60-90
rank_denominator = max(60, top_k * 6)

# Pour chaque item, a son rang (1-indexed) dans sa source :
rank_component = 1.0 / (rank_denominator + rank)
fused_component = (0.65 * score_norm) + (0.35 * rank_component)
entry["score"] += fused_component * weight
```

**Formule complete pour un item d'une source :**

```
fused_component = 0.65 x score_norm + 0.35 x (1 / (rank_denominator + rank))
contribution    = fused_component x weight
```

Ou :
- `score_norm` est le score normalise min-max de l'item dans sa source (plage [0.0, 1.0])
- `rank` est la position de l'item dans les resultats tries de sa source (1-indexed)
- `rank_denominator = max(60, top_k * 6)` amortit le signal de rang
- `weight` est `semantic_weight` (0.7) ou `lexical_weight` (0.3)

### Etape 4.3 -- Deduplication par ID

La fusion utilise un dictionnaire `by_id` indexe par l'identifiant du document. La resolution d'ID suit l'ordre de priorite :

```python
def _ensure_id(item):
    for key in ("id", "evidence_id", "document_id"):
        value = item.get(key)
        if value:
            return str(value)
    return ""
```

**Comportement pour un document trouve par les deux sources :**

```python
entry = by_id.setdefault(item_id, {
    "id": item_id,
    "score": 0.0,            # score fusionne cumulatif
    "semantic_score": 0.0,   # meilleur score semantique brut
    "lexical_score": 0.0,    # meilleur score lexical brut
    "semantic_rank": None,   # rang dans les resultats semantiques
    "lexical_rank": None,    # rang dans les resultats lexicaux
    "sources": set(),        # {"semantic", "lexical"} si trouve des deux cotes
    "metadata": {...},
    "text": "...",
})
```

- Le `score` fusionne est **cumulatif** : si le doc est rang 1 en semantique ET rang 3 en lexical, ses deux contributions s'additionnent.
- Les scores bruts (`semantic_score`, `lexical_score`) gardent le **maximum** observe (`max(existant, nouveau)`).
- Les rangs sont enregistres pour chaque source (`semantic_rank`, `lexical_rank`).
- Le champ `sources` est un `set` qui contient `"semantic"`, `"lexical"`, ou les deux.
- Le `text` et `metadata` sont remplis au premier encounter, puis preserves.

### Etape 4.4 -- Finalisation et tri

```python
# ranking.py, lignes 95-102
fused = []
for entry in by_id.values():
    entry["sources"] = sorted(entry["sources"])  # set -> liste triee
    entry["score"] = round(float(entry["score"]), 6)  # arrondi a 6 decimales
    fused.append(entry)

fused.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
return fused[:top_k]
```

---

## 5. Formules de scoring -- Exemples numeriques

### Configuration par defaut

- `semantic_weight = 0.7`
- `lexical_weight = 0.3`
- `rank_denominator = max(60, 10 * 6) = 60`
- Coefficient score : `0.65`
- Coefficient rang : `0.35`

### Exemple : top_k = 10, document trouve des deux cotes

**Donnees d'entree :**

| Source | Rang | Score brut |
|--------|------|------------|
| Semantique | 1 | 0.95 |
| Lexical | 3 | 0.78 |

**Normalisation (supposons min_sem=0.5, max_sem=0.99, min_lex=0.3, max_lex=0.85) :**

```
score_norm_sem = (0.95 - 0.50) / (0.99 - 0.50) = 0.9184
score_norm_lex = (0.78 - 0.30) / (0.85 - 0.30) = 0.8727
```

**Calcul du composant fusionne :**

```
fused_sem = 0.65 * 0.9184 + 0.35 * (1 / (60 + 1))
          = 0.5970 + 0.35 * 0.01639
          = 0.5970 + 0.00574
          = 0.6027

fused_lex = 0.65 * 0.8727 + 0.35 * (1 / (60 + 3))
          = 0.5673 + 0.35 * 0.01587
          = 0.5673 + 0.00555
          = 0.5729
```

**Score final :**

```
score_total = fused_sem * 0.7 + fused_lex * 0.3
            = 0.6027 * 0.7 + 0.5729 * 0.3
            = 0.4219 + 0.1719
            = 0.5938
```

Ce document, trouve par les deux sources, cumule les contributions et obtient un score eleve.

### Exemple : document trouve uniquement en semantique

**Donnees :** rang 2, score brut 0.88, meme normalisation que ci-dessus.

```
score_norm_sem = (0.88 - 0.50) / (0.99 - 0.50) = 0.7755

fused_sem = 0.65 * 0.7755 + 0.35 * (1 / 62)
          = 0.5041 + 0.00565
          = 0.5097

score_total = 0.5097 * 0.7 + 0.0 * 0.3
            = 0.3568
```

### Exemple : document trouve uniquement en lexical

**Donnees :** rang 1, score brut 0.85.

```
score_norm_lex = (0.85 - 0.30) / (0.85 - 0.30) = 1.0  (meilleur score lexical)

fused_lex = 0.65 * 1.0 + 0.35 * (1 / 61)
          = 0.65 + 0.00574
          = 0.6557

score_total = 0.0 * 0.7 + 0.6557 * 0.3
            = 0.1967
```

**Observation :** meme le meilleur resultat lexical seul (0.1967) obtient un score inferieur a un resultat semantique moyen (0.3568), ce qui reflete la ponderation 70/30.

### Exemple : degradation -- echec semantique

Si `NextPlaidClient.search()` leve une exception :
- `semantic_results = []`
- `semantic_norm = {}`
- `lexical_results` contient les resultats locaux

La fusion ne merge que les resultats lexicaux :

```
fused_lex = 0.65 * score_norm_lex + 0.35 * rank_component
score_total = 0.0 * 0.7 + fused_lex * 0.3
```

Le systeme retourne donc les resultats lexicaux, avec un score reduit par le poids 0.3, mais **fonctionnel**.

---

## 6. Gestion des erreurs

### Erreur semantique

```python
# pipeline.py, lignes 64-74
except Exception as exc:
    semantic_error = str(exc)
    semantic_results = []
    semantic_candidate_count = 0
    logger.warning(
        "semantic search failed index=%s strategy=%s query_len=%s error=%s",
        index_name, strategy, len(query), exc,
    )
```

**Comportement :**
- L'exception est capturee (toute exception, pas seulement les erreurs reseau).
- Les resultats semantiques sont vides.
- L'erreur est journalisee en `WARNING` avec le contexte (index, strategie, longueur de requete).
- Le champ `semantic_error` est inclus dans la reponse finale pour le debogage.
- La pipeline continue et fusionne avec les resultats lexicaux seuls.

### Erreur lexicale

La recherche lexicale (locale, synchrone) n'a pas de try/catch dedie. Une exception lexicale **propagerait** et ferait echouer la pipeline entiere. C'est un choix architectural : le lexical etant purement local et deterministe, une erreur est consideree comme un bug, pas une degradation de service.

### Propagation dans la reponse

```python
# pipeline.py, lignes 143-156
return {
    "status": "completed",
    "query": query,
    "index_name": index_name,
    "strategy": strategy,
    "count": len(ranked_results),
    "results": ranked_results,
    "latency_ms": latency_ms,
    "candidate_count": candidate_count,       # IDs uniques des deux sources
    "candidate_kept_count": candidate_kept_count,  # apres fusion + top_k
    "trace_id": trace_id,
    "semantic_error": semantic_error,         # None si OK, message sinon
    "semantic_top_k_internal": semantic_top_k_internal,
}
```

---

## 7. Telemetrie et observabilite

### Traces Langfuse

Deux evenements sont emis pour chaque recherche hybride :

1. **Trace principale** (`search.run`) : contient les parametres d'entree et les metriques de latence.
2. **Evenement de resultats** (`search.results`) : contient le nombre de resultats et les metadonnees de la recherche.

```python
trace_id = self.tracker.trace(
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
self.tracker.event(
    trace_id=trace_id,
    name="search.results",
    output={"count": len(ranked_results)},
    metadata={...},
)
```

### Span interne

```python
with start_span("search.pipeline.run", {
    "index_name": index_name,
    "strategy": strategy,
    "top_k": top_k,
}):
```

### Metriques par resultat fusionne

Chaque resultat fusionne contient des metadonnees diagnostiques :

```python
{
    "id": "doc_42",
    "score": 0.593832,
    "semantic_score": 0.95,        # score brut semantique (ou 0.0 si absent)
    "lexical_score": 0.78,         # score brut lexical (ou 0.0 si absent)
    "semantic_rank": 1,            # rang semantique (ou None si absent)
    "lexical_rank": 3,             # rang lexical (ou None si absent)
    "sources": ["lexical", "semantic"],  # sources triees
    "text": "...",
    "metadata": {...},
}
```

---

## 8. Evaluation dans le pipeline d'experiences

### Methode `evaluate_search`

Dans `app/eval/runner.py`, la strategie hybrid est evaluee au meme titre que les autres :

```python
# eval/runner.py
selected = strategies or ["baseline", "lexical", "semantic", "hybrid", "rg"]
```

Pour chaque echantillon, si la strategie est `"hybrid"` :

```python
results = await self.search_pipeline.run(
    query=sample.query,
    index_name=index_name,
    top_k=top_k,
    strategy=strategy,
)
```

Le `semantic_top_k_internal` est extrait de la reponse pour les metriques :

```python
semantic_top_k_internal = int(run.get("semantic_top_k_internal", top_k))
```

### Comparaison multi-strategies

```python
async def evaluate_search_strategies(self, samples, corpus, strategies=None, top_k=10):
    selected = strategies or ["baseline", "lexical", "semantic", "hybrid", "rg"]
    reports = {}
    for strategy in selected:
        reports[strategy] = await self.evaluate_search(
            samples=samples, corpus=corpus, strategy=strategy, top_k=top_k,
        )
```

Chaque strategie est evaluee sur les **memes donnees** (meme corpus, memes echantillons) pour une comparaison equitable. Le corpus est indexe une fois via `_index_experiment_corpus()` avant les evaluations.

---

## 9. Comparaison avec les autres strategies

| Critere | Hybrid | Semantique | Lexical | RG (regex) |
|---------|--------|------------|---------|------------|
| **Service externe** | NextPlaid | NextPlaid | Non | Non |
| **GPU requis** | Oui | Oui | Non | Non |
| **Temps de reponse** | ~50-200 ms | ~50-200 ms | ~1-5 ms | ~1-10 ms |
| **Fautes de frappe** | Oui (sem) | Oui | Partiel (trigr.) | Non |
| **Synonymes** | Oui (sem) | Oui | Non | Non |
| **Termes exacts** | Oui (lex) | Approximatif | Exact | Exact |
| **Regex** | Non | Non | Via planificateur | Natif |
| **Deterministe** | Non | Non | Oui | Oui |
| **Tolerance pannes** | Oui (fallback lexical) | Non | Oui | Oui |
| **Couverture** | Large | Large | Etroite | Etroite |
| **Cout LLM** | 0 | 0 | 0 | 0 |
| **Pool de candidats** | Elargi (x3, max 50) | Standard | Standard | Standard |

### Quand utiliser chaque strategie

| Cas d'usage | Strategie recommandee |
|-------------|----------------------|
| Recherche generale dans documents reglementaires | **hybrid** |
| Comprehension conceptuelle, questions en langage naturel | semantic |
| Recherche de numeros d'articles, codes, references exactes | lexical |
| Recherche par motifs (`art.*12[0-9]`) | rg |
| Performance maximale, latence minimale | lexical |
| Robustesse maximale, tolerance aux pannes | **hybrid** |

---

## 10. Points forts et limites

### Points forts

- **Couverture maximale** -- Combine les forces du semantique (comprehension, synonymes) et du lexical (correspondances exactes, termes techniques). Les documents trouves par les deux sources sont naturellement promus.
- **Degradation gracieuse** -- Si le service semantique est indisponible, le systeme continue de fonctionner avec les resultats lexicaux. Aucune panne totale.
- **Elargissement du pool** -- Le `semantic_top_k_internal` permet de recuperer davantage de candidats semantiques, augmentant les chances de trouver des documents pertinents que la fusion pourra promouvoir.
- **Signal de rang** -- La fusion combine non seulement les scores mais aussi les rangs, ce qui privilegie les resultats bien classes dans les deux sources.
- **Observabilite** -- Chaque resultat fusionne contient les scores bruts, les rangs et les sources de chaque signal, facilitant le diagnostic.
- **Pas de surcout LLM** -- La fusion est purement algorithmique (pas d'appel a un modele de langage supplementaire).

### Limites

- **Latence additive** -- En mode hybride actuel, la recherche lexicale attend la fin de la recherche semantique (pas de parallelisme effectif). La latence est la somme des deux recherches.
- **Ponderation statique** -- Les poids (70/30) sont fixes. Ils ne s'adaptent pas a la qualite des resultats de chaque source pour une requete donnee. Une requete tres technique pourrait beneficier d'un poids lexical plus eleve.
- **Normalisation fragile** -- La normalisation min-max depend des scores minimum et maximum de la requete. Si un seul resultat semantique est retourne, tous les scores normalises valent 1.0, ce qui elimine le signal de score au profit du rang uniquement.
- **Pas de reciproque pour le lexical** -- Si la recherche lexicale echoue (exception), toute la pipeline echoue. Il n'y a pas de fallback symetrique.
- **Pas de score de confiance** -- Le systeme ne produit pas de score de confiance global qui indiquerait si la fusion est fiable (ex : peu de chevauchement entre les deux sources).
- `rank_denominator` fixe -- La valeur `max(60, top_k * 6)` est calibree pour `top_k = 10` (donnant 60). Pour des valeurs de `top_k` tres differentes, le signal de rang peut etre trop fort ou trop faible.
