# Strategie de Recherche Baseline — Documentation Complete

## Vue d'ensemble

La strategie **baseline** (`strategy="baseline"`) est un moteur de recherche lexicale minimaliste, entierement en memoire, qui sert de **reference de base** (point de comparaison) pour evaluer les performances des strategies plus avancees (lexical, semantic, hybrid, rg).

Contrairement a la strategie lexicale complete qui utilise un index de trigrammes et un index inverse avec des structures de donnees persistantes, la baseline fonctionne par **balayage lineaire complet** (*full scan*) du corpus a chaque requete. Elle ne construit aucun index, ne depend d'aucun service externe et ne requiert ni GPU ni embedding.

Son role est de repondre a la question : *"Quel niveau de performance peut-on atteindre avec l'approche la plus simple possible ?"*

---

## Architecture des composants

```
EvaluationRunner.evaluate_search(strategy="baseline")
  |
  +-- BaselineLexicalRetriever.search(query, corpus, top_k)
        |
        +-- _normalize(query)         -> texte normalise
        +-- _tokenize(query)          -> ensemble de tokens
        |
        +-- Pour chaque document du corpus (full scan) :
        |     +-- _normalize(text)
        |     +-- _tokenize(text)
        |     +-- token_overlap = |tokens_query & tokens_doc| / |tokens_query|
        |     +-- phrase_bonus   = query_norm in doc_norm ? 1.0 : 0.0
        |     +-- score = 0.8 * token_overlap + 0.2 * phrase_bonus
        |
        +-- Tri par score decroissant
        +-- Retour des top_k premiers
```

**Fichiers sources :**

| Fichier | Role |
|---------|------|
| `app/eval/baseline.py` | Implementation complete de la baseline |
| `app/eval/runner.py` | Orchestration des evaluations, appel de la baseline |
| `app/eval/models.py` | Modele `SearchEvalSample` (requetes + IDs pertinents) |
| `app/eval/metrics.py` | Metriques NDCG, MRR, Recall, Precision |

---

## 1. Fonctions utilitaires

### Normalisation (`_normalize`)

```python
def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
```

Transforme le texte en minuscules, remplace les sequences d'espaces par un seul espace, et supprime les espaces en debut/fin.

**Effets :**
- `"  Hello   World  "` devient `"hello world"`
- Les caracteres accentues sont conserves tels quels (pas de translitteration)
- La casse est uniformisee pour permettre la comparaison

### Tokenisation (`_tokenize`)

```python
def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize(value)))
```

Extrait toutes les sequences de caracteres alphanumeriques (a-z, 0-9) du texte normalise et les retourne sous forme d'**ensemble** (sans doublons).

**Effets :**
- `"Hello World 123"` produit `{"hello", "world", "123"}`
- La ponctuation est ignoree
- Les termes frequencies sont perdues (pas de comptage, pas de TF-IDF)
- Les mots vides (*stop words*) ne sont pas filtres

**Difference avec la strategie lexicale :** La tokenisation lexicale retourne une `list[str]` (avec doublons, pour comptage TF), tandis que la baseline retourne un `set[str]` (sans doublons, intersection simple).

---

## 2. Algorithme de recherche (`search`)

### Signature

```python
def search(self, query: str, corpus: list[dict], top_k: int = 10) -> list[dict]:
```

| Parametre | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | — | Texte de la requete |
| `corpus` | `list[dict]` | — | Liste de documents `{"id": ..., "text": ..., "metadata": ...}` |
| `top_k` | `int` | `10` | Nombre maximum de resultats |

### Etape 1 — Preparation de la requete

```python
q_norm = _normalize(query)
q_tokens = _tokenize(query)
if not q_norm:
    return []
```

La requete est normalisee et tokenisee une seule fois, avant la boucle de parcours. Si la requete est vide apres normalisation, on retourne immediatement une liste vide.

### Etape 2 — Balayage complet du corpus (full scan)

```python
for row in corpus:
    row_id = str(row.get("id", ""))
    text = str(row.get("text", ""))
    if not row_id or not text:
        continue
```

Chaque document du corpus est examine sequentiellement. Les documents sans ID ou sans texte sont ignores.

**Complexite :** O(n) ou n est la taille du corpus. Chaque document est normalise et tokenise a la volee — il n'y a aucun pre-traitement ni index.

### Etape 3 — Calcul du chevauchement de tokens

```python
d_norm = _normalize(text)
d_tokens = _tokenize(text)

token_overlap = (len(q_tokens & d_tokens) / len(q_tokens)) if q_tokens else 0.0
```

**Formule :**

```
token_overlap = |tokens_query INTER tokens_doc| / |tokens_query|
```

C'est un **Jaccard oriente requete** : on mesure la proportion de tokens de la requete qui sont presents dans le document. Contrairement a un Jaccard classique, on ne divise pas par l'union mais uniquement par le nombre de tokens de la requete.

| Situation | `q_tokens` | `d_tokens` | Intersection | Score |
|-----------|------------|------------|--------------|-------|
| Match parfait | `{"a","b"}` | `{"a","b","c"}` | `{"a","b"}` | 1.0 |
| Match partiel | `{"a","b","c"}` | `{"a","x","y"}` | `{"a"}` | 0.333 |
| Aucun match | `{"x","y"}` | `{"a","b"}` | `{}` | 0.0 |

**Plage :** [0.0, 1.0]

### Etape 4 — Bonus de phrase exacte

```python
phrase_bonus = 1.0 if q_norm in d_norm else 0.0
```

Un bonus binaire (0.0 ou 1.0) est accorde si la requete entiere (normalisee) apparait comme sous-chaine exacte dans le texte du document (normalise).

**Exemples :**
- Requete `"hello world"` dans `"say hello world today"` -> bonus = 1.0
- Requete `"hello world"` dans `"world of hello"` -> bonus = 0.0 (ordre different)

### Etape 5 — Score composite

```python
score = (0.8 * token_overlap) + (0.2 * phrase_bonus)
if score == 0.0:
    continue
```

**Formule finale :**

```
score = 0.8 * token_overlap + 0.2 * phrase_bonus
```

| Composant | Poids | Plage | Capture |
|-----------|-------|-------|---------|
| Token overlap | 80% | [0.0, 1.0] | Presence de mots-cles en commun |
| Phrase bonus | 20% | {0.0, 1.0} | Correspondance exacte de la requete |

**Plage theorique :** [0.0, 1.0]
- Score maximum 1.0 = tous les tokens presents + phrase exacte
- Score minimum > 0 = au moins un token commun ou phrase exacte

**Filtrage :** Les documents avec un score de 0.0 sont exclus des resultats (ni token commun, ni phrase correspondante).

### Etape 6 — Construction du resultat

```python
results.append({
    "id": row_id,
    "score": round(score, 6),
    "text": text,
    "metadata": dict(row.get("metadata", {})),
    "source": "baseline",
})
```

Chaque resultat contient :
- `id` : identifiant du document (chaine)
- `score` : score composite arrondi a 6 decimales
- `text` : texte original du document
- `metadata` : metadonnees du document
- `source` : toujours `"baseline"` (permet d'identifier la provenance)

### Etape 7 — Tri et selection

```python
results.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
return results[:top_k]
```

Les resultats sont tries par score decroissant, puis tronques a `top_k` elements.

---

## 3. Formules de scoring — Resume detaille

### Formule principale

```
score = 0.80 * (|Q INTER D| / |Q|) + 0.20 * I(q in d)
```

Ou :
- `Q` = ensemble des tokens de la requete
- `D` = ensemble des tokens du document
- `|Q INTER D|` = cardinalite de l'intersection
- `I(q in d)` = indicateur binaire (1 si la requete est sous-chaine du document, 0 sinon)

### Distribution des scores possibles

| Scenario | token_overlap | phrase_bonus | Score final |
|----------|--------------|--------------|-------------|
| Aucun token commun | 0.0 | 0.0 | 0.0 (exclu) |
| Tokens partiels, pas de phrase | 0.5 | 0.0 | 0.40 |
| Tous les tokens, pas de phrase | 1.0 | 0.0 | 0.80 |
| Tokens partiels + phrase exacte | 0.5 | 1.0 | 0.60 |
| Tous les tokens + phrase exacte | 1.0 | 1.0 | 1.00 |

### Comparaison avec la formule lexicale

| Aspect | Baseline | Lexicale |
|--------|----------|----------|
| Composant principal | Token overlap (80%) | Trigram overlap (55%) |
| Composant secondaire | Phrase bonus (20%) | Token match (35%) |
| Bonus exact | Phrase bonus (20%) | Phrase bonus (10%) |
| Sensibilite aux fautes | Aucune | Elevee (trigrammes) |
| Structures d'index | Aucune | TrigramIndex + InvertedIndex |
| Pre-filtrage des candidats | Non (full scan) | Oui (intersection/union) |

---

## 4. Flux d'execution complet dans le contexte d'evaluation

### Contexte : EvaluationRunner

La baseline n'est **jamais** appelee depuis la pipeline de recherche principale (`SearchPipeline.run()`). Elle est exclusivement utilisee dans le cadre de l'evaluation comparative des strategies.

```python
# runner.py
class EvaluationRunner:
    def __init__(self, search_pipeline, baseline_retriever):
        self.search_pipeline = search_pipeline or SearchPipeline()
        self.baseline_retriever = baseline_retriever or BaselineLexicalRetriever()
```

### Etape 1 — Selection de la strategie

```python
# runner.py - evaluate_search()
if strategy == "baseline":
    baseline_start = perf_counter()
    results = self.baseline_retriever.search(sample.query, corpus=corpus, top_k=top_k)
    latency_ms = round((perf_counter() - baseline_start) * 1000.0, 3)
    candidate_count = len(corpus)
```

Quand `strategy="baseline"`, le retriever baseline est appele directement avec le corpus complet. Aucune indexation prealable n'est necessaire.

### Etape 2 — Passage du corpus brut

Contrairement aux autres strategies qui utilisent un index pre-construit, la baseline recoit le corpus sous forme de liste de dictionnaires :

```python
corpus = [
    {"id": "doc-1", "text": "Le reglement ...", "metadata": {...}},
    {"id": "doc-2", "text": "Article 3 ...", "metadata": {...}},
    ...
]
```

**Avantage :** Pas besoin d'indexer le corpus avant l'evaluation.
**Inconvenient :** Le corpus entier est parcouru a chaque requete.

### Etape 3 — Calcul des metriques

```python
retrieved_ids = [str(item.get("id", "")) for item in results if item.get("id")]

# Metriques calculees pour chaque echantillon :
recall_at_k  = recall_at_k(sample.relevant_ids, retrieved_ids, k=top_k)
mrr_value    = mrr(sample.relevant_ids, retrieved_ids)
ndcg_value   = ndcg_at_k(relevance_map, retrieved_ids, k=top_k)
```

### Etape 4 — Agregation des resultats

```python
return {
    "strategy": "baseline",
    "top_k": top_k,
    "samples": count,
    "mean_recall_at_k": ...,
    "mean_mrr": ...,
    "mean_ndcg_at_k": ...,
    "mean_latency_ms": ...,
    "mean_candidate_count": ...,
    "mean_candidate_kept_count": ...,
    "rows": rows,
}
```

---

## 5. Comparaison multi-strategies

### Tableau comparatif

| Critere | Baseline | Lexical | Semantic | Hybrid | RG (regex) |
|---------|----------|---------|----------|--------|------------|
| Service externe | Non | Non | NextPlaid | NextPlaid | Non |
| GPU requis | Non | Non | Oui | Oui | Non |
| Structures d'index | Aucune | Trigrammes + Inverse | Embeddings | Les deux | Full scan + regex |
| Pre-filtrage candidats | Non | Oui | Oui | Oui | Oui (trigrammes) |
| Mode de parcours | Full scan | Index | Index | Index | Full scan |
| Fautes de frappe | Non | Oui (trigrammes) | Oui | Oui | Non |
| Synonymes | Non | Non | Oui | Oui | Non |
| Regex | Non | Via planificateur | Non | Non | Natif |
| Deterministe | Oui | Oui | Non | Non | Oui |
| Indexation prealable | Non requise | Requise | Requise | Requise | Requise |
| Latence typique | ~1-10 ms | ~1-5 ms | ~50-200 ms | ~50-200 ms | ~1-10 ms |
| Cout LLM | 0 | 0 | 0 | 0 | 0 |

### Place dans la hierarchie des strategies

```
Baseline (simple)
   |
   +-- Lexical (baseline + trigrammes + index inverse)
         |
         +-- Semantic (embeddings + similarite vectorielle)
               |
               +-- Hybrid (lexical + semantic + fusion ponderee)
               +-- RG (lexical + expressions regulieres)
```

La baseline est le **plancher** de performance. Toute strategie plus elaboree doit logiquement la surpasser sur les metriques de rappel et de precision.

---

## 6. Utilisation dans les experiences

### Appel via EvaluationRunner

```python
#runner.py - evaluate_search_strategies()
selected = strategies or ["baseline", "lexical", "semantic", "hybrid", "rg"]
```

La baseline est toujours incluse par defaut dans les comparaisons multi-strategies.

### Skipped indexing

```python
# runner.py - run_find_experiment()
needs_index = any(strategy != "baseline" for strategy in selected)
if needs_index:
    await self._index_experiment_corpus(corpus=pack["corpus"], index_name=index_name)
```

La baseline ne necessite pas d'indexation du corpus. L'indexation n'est effectuee que si au moins une autre strategie est testee en parallele.

### Datasets supportes

La baseline fonctionne avec tous les datasets charges par le runner :
- **kensho/FIND** (via `load_find_eval_pack`)
- **ibm-research/Wikipedia_contradict_benchmark** (via `load_wikipedia_contradict_eval_pack`)

---

## 7. Parametres et configuration

### Parametres de recherche

| Parametre | Type | Default | Description |
|-----------|------|---------|-------------|
| `top_k` | `int` | `10` | Nombre maximum de resultats retournes |

### Parametres de scoring (codés en dur)

| Parametre | Valeur | Description |
|-----------|--------|-------------|
| `token_overlap_weight` | `0.8` | Poids du chevauchement de tokens |
| `phrase_bonus_weight` | `0.2` | Poids du bonus de phrase exacte |

> **Note :** Contrairement a la strategie lexicale et au mode hybrid, ces poids ne sont **pas configurables** via des variables d'environnement ou un fichier de configuration. Ils sont definis en dur dans le code source.

### Parametres d'evaluation

| Parametre | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_samples` | `int` | `100` | Nombre maximum d'echantillons par experience |
| `max_query_chars` | `int` | `8192` | Longueur maximale des requetes |

---

## 8. Points forts et limites

### Points forts

- **Simplicite maximale** — 50 lignes de code, aucun index, aucune dependance
- **Zero latence reseau** — tout est local et en memoire
- **Deterministe** — memes requetes, memes resultats, toujours
- **Pas d'indexation requise** — fonctionne immediatement sur n'importe quel corpus
- **Cout nul** — pas de modele, pas d'API, pas de calcul GPU
- **Reproductible** — aucune composante aleatoire ou non-deterministe
- **Reference de comparaison** — definit le plancher de performance pour l'evaluation
- **Tokenisation rapide** — pas de stemming, pas de lemmatisation, pas d'analyse morphologique

### Limites

- **Pas de comprehension semantique** — "voiture" ne correspond pas a "automobile"
- **Pas de tolérance aux fautes** — contrairement aux trigrammes, un seul caractere different rend un token incompatible
- **Pas de stemming** — "reglement" ne correspond pas a "reglements"
- **Full scan obligatoire** — la complexite est toujours O(n) par requete, inadapte aux grands corpus
- **Tokenisation basique** — ne gere pas le francais avance (accents traites comme separateurs implicites via la regex `[a-z0-9]+`)
- **Pas de TF-IDF** — la frequence des termes est ignoree, seul le booléen "present/absent" compte
- **Pas de support regex** — contrairement a la strategie RG et lexicale
- **Poids fixes** — les ponderations (0.8/0.2) ne sont pas ajustables sans modification du code
- **Sous-performante par conception** — sert de plancher, pas de strategie de production
