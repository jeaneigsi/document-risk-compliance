# Stratégie de Recherche Lexicale — Documentation Complète

## Vue d'ensemble

La stratégie **lexicale** (`strategy="lexical"`) est un moteur de recherche local, entièrement en mémoire, qui combine deux structures d'index classiques — un **index de trigrammes** et un **index inversé** — pour retrouver des unités de preuve (*evidence units*) pertinentes sans recourir à un modèle sémantique.

Contrairement à la recherche sémantique (NextPlaid), elle ne nécessite aucun service externe, aucune GPU et aucun embedding. Elle fonctionne par correspondance exacte ou approximative de texte.

---

## Architecture des composants

```
SearchPipeline.run(strategy="lexical")
  │
  ├── LocalSearchRegistry.lexical_search()
  │     │
  │     └── CursorLikeIndex.search()
  │           │
  │           ├── TrigramIndex      (55% du score)
  │           ├── InvertedIndex     (35% du score)
  │           └── Phrase Bonus      (10% du score)
  │
  └── Résultats triés par score décroissant, top_k retournés
```

**Fichiers sources :**

| Fichier | Rôle |
|---------|------|
| `app/search/pipeline.py` | Orchestration de la pipeline |
| `app/search/local_registry.py` | Registre des indexes en mémoire |
| `app/search/cursor_like.py` | Index trigrammes + inversé + scoring |
| `app/search/regex_planner.py` | Planification des requêtes regex |
| `app/search/ranking.py` | Fusion des résultats (hybride) |
| `app/search/evidence.py` | Modèle EvidenceUnit |

---

## 1. TrigramIndex — Index de trigrammes (55%)

### Principe

Un **trigramme** est une sous-chaîne de 3 caractères consécutifs. Pour un texte `"hello"`, les trigrammes sont : `{"hel", "ell", "llo"}`.

L'index stocke pour chaque trigramme l'ensemble des IDs de documents qui le contiennent.

### Structures de données

```python
class TrigramIndex:
    postings: dict[str, set[str]]    # trigramme → {doc_id, ...}
    doc_trigrams: dict[str, set[str]]  # doc_id → {trigrammes du doc}
    doc_ids: set[str]                  # tous les doc_ids indexés
```

### Indexation (`add`)

```python
def add(self, doc_id: str, text: str):
    trigs = _trigrams(text.lower())          # extraire les trigrammes
    for trig in trigs:
        self.postings[trig].add(doc_id)      # posting list
    self.doc_trigrams[doc_id] = trigs         # stockage inverse
    self.doc_ids.add(doc_id)
```

### Recherche de candidats (`candidates`)

```python
def candidates(self, query: str) -> set[str]:
    q_trigs = _trigrams(query.lower())
    # Intersection des postings de chaque trigramme de la requête
    return set.intersection(*[self.postings[t] for t in q_trigs])
```

**Seuls les documents contenant TOUS les trigrammes de la requête sont candidats.** C'est un filtre d'abord très sélectif.

### Score de chevauchement (`overlap_ratio`)

```python
def overlap_ratio(self, doc_id: str, query: str) -> float:
    q_trigs = _trigrams(query.lower())
    d_trigs = self.doc_trigrams[doc_id]
    return len(q_trigs & d_trigs) / len(q_trigs)
```

Résultat entre 0.0 et 1.0 : proportion des trigrammes de la requête présents dans le document.

**Pourquoi 55% ?** Le trigramme capture les fautes de frappe, les variations morphologiques et les correspondances partielles. C'est le signal le plus robuste pour du texte technique/juridique.

---

## 2. InvertedIndex — Index inversé tokenisé (35%)

### Principe

Index classique de recherche d'information : chaque **token** (mot) est associé à la liste des documents qui le contiennent, avec sa fréquence.

### Structures de données

```python
class InvertedIndex:
    postings: dict[str, set[str]]      # token → {doc_id, ...}
    doc_tf: dict[str, Counter[str]]    # doc_id → {token: fréquence}
```

### Tokenisation

```python
def _tokenize(text: str) -> list[str]:
    # Extraction des séquences alphanumériques, lowercasées
    return re.findall(r"[a-z0-9]+", text.lower())
```

> Note : Il n'y a **pas de stemming** ni de **stop words**. La tokenisation est intentionnellement simple pour rester déterministe et prévisible.

### Indexation (`add`)

```python
def add(self, doc_id: str, text: str):
    tokens = _tokenize(text)
    tf = Counter(tokens)                # fréquence des termes
    self.doc_tf[doc_id] = tf
    for token in tf:
        self.postings[token].add(doc_id)
```

### Recherche de candidats (`candidates`)

```python
def candidates(self, query: str) -> set[str]:
    q_tokens = _tokenize(query)
    # Union des postings : au moins un token doit matcher
    return set.union(*[self.postings[t] for t in q_tokens])
```

**Attention :** Contrairement au trigramme (intersection stricte), l'inversé utilise une **union** — un seul token commun suffit pour être candidat.

### Score de correspondance (`token_score`)

```python
def token_score(self, doc_id: str, query: str) -> float:
    tf = self.doc_tf.get(doc_id, Counter())
    q_tokens = _tokenize(query)
    matches = sum(1 for t in q_tokens if tf.get(t, 0) > 0)
    return matches / len(q_tokens)
```

Proportion des tokens de la requête trouvés dans le document. Un score de 1.0 = tous les mots présents.

**Pourquoi 35% ?** L'index inversé capture les correspondances au niveau "mot". C'est un signal plus grossier mais complémentaire au trigramme.

---

## 3. Phrase Bonus — Correspondance exacte (10%)

### Principe

Un bonus binaire (0.0 ou 1.0) accordé si la requête entière apparaît comme sous-chaîne exacte dans le texte du document.

```python
phrase_bonus = 1.0 if query.lower() in doc_text.lower() else 0.0
```

### Pourquoi seulement 10% ?

La correspondance exacte est rare dans les documents réglementaires (variantes de formulation, numéros qui changent). Le bonus existe pour départager les ex-æquo, pas pour dominer le score.

---

## 4. Formule de scoring composite

Le score final d'un candidat lexical est :

```
score = 0.55 × trigram_overlap_ratio
      + 0.35 × token_match_ratio
      + 0.10 × phrase_bonus
```

| Composant | Poids | Plage | Capture |
|-----------|-------|-------|---------|
| Trigram overlap | 55% | [0.0, 1.0] | Correspondances partielles, fautes, variations |
| Token match | 35% | [0.0, 1.0] | Présence de mots-clés |
| Phrase bonus | 10% | {0.0, 1.0} | Match exact de la requête |

**Plage théorique :** [0.0, 1.0]
- Score maximum 1.0 = tous les trigrammes + tous les tokens + phrase exacte
- Score minimum > 0 = au moins un signal positif

---

## 5. Flux d'exécution complet

### Étape 1 — Réception de la requête

```python
# pipeline.py
async def run(query, index_name, top_k=10, strategy="lexical"):
    ...
    if strategy in ("lexical", "hybrid"):
        lexical_results = self.registry.lexical_search(
            index_name=index_name,
            query=query,
            top_k=top_k,
        )
```

### Étape 2 — Routage vers l'index local

```python
# local_registry.py
def lexical_search(self, index_name, query, top_k=10):
    return self._indexes[index_name].search(query=query, top_k=top_k)
```

Chaque `index_name` a son propre `CursorLikeIndex` (isolé des autres indexes).

### Étape 3 — Détection de regex

```python
# cursor_like.py
def search(self, query, top_k=10):
    plan = build_regex_query_plan(query)
    if plan and plan.is_regex:
        return self._search_regex(plan.pattern, plan.flags, plan.clauses, top_k)
    # Sinon : recherche lexicale standard (voir étape 4)
```

Si la requête contient des métacaractères (`*`, `+`, `[`, etc.) ou commence par `/pattern/flags`, le système bascule en mode regex optimisé.

### Étape 4 — Recherche lexicale standard

```
1. TrigramIndex.candidates(query)  → ensemble de candidats par intersection
2. InvertedIndex.candidates(query) → ensemble de candidats par union
3. Union des deux ensembles
4. Pour chaque candidat :
   a. trigram_score = TrigramIndex.overlap_ratio(doc_id, query)
   b. token_score   = InvertedIndex.token_score(doc_id, query)
   c. phrase_bonus  = query in doc_text ? 1.0 : 0.0
   d. score         = 0.55×a + 0.35×b + 0.10×c
5. Tri par score décroissant
6. Retour des top_k premiers
```

### Étape 5 — Construction du résultat

```python
result = {
    "id": doc_id,
    "score": score,
    "text": doc_text,
    "metadata": doc_metadata,
    "source": "lexical"
}
```

---

## 6. Mode Regex — Recherche par expressions régulières

### Détection

```python
# regex_planner.py
def build_regex_query_plan(query):
    if query.startswith("/") or has_meta_chars(query):
        # Parser la regex et extraire les clauses trigrammes
        parsed = sre_parse.parse(pattern, flags)
        clauses = _subpattern_clauses(parsed)
        return RegexQueryPlan(is_regex=True, pattern=pattern, flags=flags, clauses=clauses)
    return None
```

### Optimisation

Au lieu de tester la regex sur **tous** les documents, le planner extrait les trigrammes contenus dans la regex (littéraux) et les utilise comme **pré-filtre** :

```
Exemple : /article.*3[0-9]+/
  → trigrammes extraits : "art", "rti", "tic", "icl", "cle"
  → Seuls les docs contenant ces trigrammes sont testés avec la regex
```

### Scoring regex

```python
def rg_search(self, query, top_k=10):
    matches = list(compiled.finditer(text))
    if matches:
        score = min(1.0, 0.5 + 0.5 * (total_match_len / len(text)))
    else:
        # Fallback token-based
        score = hit_tokens / len(q_tokens)
```

| Cas | Formule |
|-----|---------|
| Regex match | `min(1.0, 0.5 + 0.5 × (longueur_match / longueur_texte))` |
| Pas de match | `tokens_trouvés / tokens_requête` |

Le seuil à 0.5 garantit qu'un match regex est toujours mieux classé qu'un match token-only.

---

## 7. Indexation des documents

### Quand les documents sont-ils indexés ?

Lors de l'appel à `SearchPipeline.index_evidence_units()` :

```python
async def index_evidence_units(self, evidence_units, index_name):
    for unit in evidence_units:
        self.registry.add(
            index_name=index_name,
            doc_id=unit.evidence_id,
            text=unit.content,
            metadata=unit.metadata,
        )
```

Chaque **EvidenceUnit** (extrait d'un document OCR) est ajoutée aux deux indexes (trigrammes + inversé) du `CursorLikeIndex` correspondant.

### Modèle EvidenceUnit

```python
class EvidenceUnit(BaseModel):
    evidence_id: str           # "doc_id:e_idx:s_idx"
    document_id: str           # Document source
    content: str               # Texte indexé et recherchable
    source_type: str           # "text_span", "layout", "markdown_block"
    page_number: int | None    # Numéro de page
    metadata: dict             # filename, spans, etc.
```

---

## 8. Comparaison avec les autres stratégies

| Critère | Lexical | Sémantique | Hybrid | RG (regex) |
|---------|---------|------------|--------|------------|
| Service externe | Non | NextPlaid | NextPlaid | Non |
| GPU requis | Non | Oui | Oui | Non |
| Temps de réponse | ~1-5 ms | ~50-200 ms | ~50-200 ms | ~1-10 ms |
| Fautes de frappe | Partiel (trigrammes) | Oui | Oui | Non |
| Synonymes | Non | Oui | Oui | Non |
| Regex | Via planificateur | Non | Non | Natif |
| Déterministe | Oui | Non | Non | Oui |
| Coût LLM | 0 | 0 | 0 | 0 |

---

## 9. Utilisation dans le mode Hybride

En stratégie `hybrid`, les résultats lexicaux sont **fusionnés** avec les résultats sémantiques via `fuse_search_results()` :

```python
# ranking.py
def fuse_search_results(semantic_results, lexical_results, top_k=10,
                       semantic_weight=0.7, lexical_weight=0.3):
```

### Formule de fusion

1. **Normalisation min-max** des scores de chaque source
2. **Score fusionné par entrée :**

```
fused_component = 0.65 × normalized_score + 0.35 × (1 / (60 + rank))
final_score += fused_component × weight
```

3. **Poids par défaut :** sémantique = 70%, lexical = 30%
4. **Déduplication** par ID de document (on garde le meilleur score)

Le lexical agit donc comme un **signal complémentaire** qui peut remonter des résultats que le sémantique a manqués (termes techniques, numéros d'articles, codes exacts).

---

## 10. Points forts et limites

### Points forts
- **Zéro latence réseau** — tout est en mémoire
- **Déterministe** — mêmes requêtes, mêmes résultats
- **Regex natif** — idéal pour les motifs récurrents (articles, numéros)
- **Coût nul** — pas de modèle, pas d'API
- **Complémentaire** — capture ce que le sémantique rate

### Limites
- **Pas de compréhension sémantique** — "voiture" ≠ "automobile"
- **Pas de stemming** — "réglement" ≠ "réglements"
- **Index en mémoire uniquement** — pas de persistance entre redémarrages
- **Tokenisation simple** — ne gère pas le français avancé (accents, élisions)
