# Strategie de Recherche RG (ripgrep/regex) — Documentation Complete

## Vue d'ensemble

La strategie **rg** (`strategy="rg"`) est un moteur de recherche en texte integre par expressions regulieres, inspire du comportement de l'outil `ripgrep` (rg). Contrairement a la strategie lexicale qui utilise un index de trigrammes et un index inverse pour prefiltrer les candidats, la strategie rg effectue un **scan complet** de tous les documents, avec une alternative a la correspondance par tokens si la regex echoue.

La strategie rg est concue comme un **baseline deterministe** pour les benchmarks d'evaluation. Elle repond a la question : *"Que donnerait une recherche texte brute, sans index, sans modele, sans heuristique ?"* C'est le plancher de reference contre lequel mesurer les gains des strategies lexicale, semantique et hybride.

### Principes fondamentaux

| Aspect | Description |
|--------|-------------|
| **Approche** | Scan lineaire complet de tous les documents |
| **Detection regex** | Automatique via `regex_planner` (metacaracteres ou syntaxe `/pattern/flags`) |
| **Fallback** | Recherche tokenisee si la requete n'est pas une regex valide |
| **Index** | Aucun prefiltrage par index ; les structures d'index existent mais ne sont pas utilisees |
| **Scoring** | Base sur la densite de correspondance (regex) ou le ratio de tokens (fallback) |
| **Source** | `"rg"` dans les resultats |

---

## Architecture des composants

```
SearchPipeline.run(strategy="rg")
  |
  +-- LocalSearchRegistry.rg_search(index_name, query, top_k)
        |
        +-- CursorLikeIndex.rg_search(query, top_k)
              |
              +-- regex_planner.build_regex_query_plan(query)
              |     |
              |     +-- parse_regex_query(query)
              |     |     |-- Detection syntaxe /pattern/flags
              |     |     |-- Detection metacaracteres
              |     |     +-- Extraction pattern + flags
              |     |
              |     +-- sre_parse.parse(pattern, flags)
              |     +-- _subpattern_clauses(parsed)
              |           |-- LITERAL -> accumulation
              |           |-- SUBPATTERN -> recursion + merge
              |           |-- BRANCH -> union de clauses
              |           |-- MAX_REPEAT / MIN_REPEAT -> conditionnel
              |           +-- Autres -> flush du tail
              |
              +-- [Chemin regex] re.compile + finditer sur chaque document
              |     |-- score = min(1.0, 0.5 + 0.5 * (total_match_len / len(text)))
              |     +-- source: "rg"
              |
              +-- [Chemin fallback] tokenisation + recherche exhaustive
                    |-- score = hit_tokens / len(q_tokens)
                    +-- source: "rg"

  +-- Resultats tries par score decroissant, top_k retournes
```

**Fichiers sources :**

| Fichier | Role |
|---------|------|
| `app/search/pipeline.py` | Orchestration de la pipeline, routage `strategy="rg"` |
| `app/search/local_registry.py` | Registre des indexes en memoire, delegation `rg_search` |
| `app/search/cursor_like.py` | Implementation `rg_search` : scan complet + scoring |
| `app/search/regex_planner.py` | Planification regex : detection, parsing, clauses trigrammes |
| `app/eval/runner.py` | Evaluation comparative multi-strategies (inclut "rg") |
| `app/search/ranking.py` | Fusion hybride (non utilise par rg seul) |

---

## 1. Le planificateur de regex (regex_planner)

### 1.1 Vue d'ensemble

Le module `regex_planner.py` est le cerveau de la detection et de l'analyse des requetes regex. Il fonctionne en trois phases :

1. **Detection** : la requete est-elle une regex ?
2. **Parsing** : decomposition de la regex en arbre syntaxique via `sre_parse`
3. **Extraction** : extraction des clauses trigrammes obligatoires pour le prefiltrage

### 1.2 Detection de regex — `parse_regex_query`

```python
def parse_regex_query(query: str) -> tuple[bool, str, int]:
```

La fonction determine si la requete est une regex et retourne un triplet `(is_regex, pattern, flags)`.

#### Methode 1 : Syntaxe `/pattern/flags`

Si la requete commence par `/`, le parser cherche le dernier `/` non echappe pour delimiter le pattern et les flags :

```
/article.*3[0-9]+/i
 ^^^^^^^^^^^^^^^^ ^   pattern="article.*3[0-9]+"  flags=re.IGNORECASE
```

La recherche du slash fermant parcourt la chaine de droite a gauche :

```python
for idx in range(len(raw) - 1, 0, -1):
    if raw[idx] == "/" and raw[idx - 1] != "\\":
        slash_idx = idx
        break
```

Flags supportes :

| Flag | Constante Python | Effet |
|------|-----------------|-------|
| `i` | `re.IGNORECASE` | Insensible a la casse |
| `m` | `re.MULTILINE` | `^` et `$` par ligne |
| `s` | `re.DOTALL` | `.` matche les retours a la ligne |
| `x` | `re.VERBOSE` | Espaces et commentaires ignores |

#### Methode 2 : Metacaracteres

Si la requete ne commence pas par `/`, le systeme verifie la presence de metacaracteres :

```python
_REGEX_META_CHARS = set(".^$*+?{}[]\\|()")

if any(ch in _REGEX_META_CHARS for ch in raw):
    return True, raw, 0
```

N'importe quel caractere parmi `.^$*+?{}[]\\|()` declenche le mode regex avec les flags par defaut (0).

#### Methode 3 : Texte simple

Si aucun metacaractere n'est present, la requete est traitee comme du texte simple :

```python
return False, raw, 0
```

### 1.3 Construction du plan — `build_regex_query_plan`

```python
def build_regex_query_plan(
    query: str,
    max_clauses: int = 64,
    max_clause_trigrams: int = 32,
) -> RegexQueryPlan | None:
```

#### Etapes

1. Appel de `parse_regex_query` pour obtenir `(is_regex, pattern, flags)`
2. Si `is_regex` est `False`, retourne un plan non-regex (utilise par la strategie lexicale pour son chemin standard)
3. Si `is_regex` est `True` :
   - **Parsing** via `sre_parse.parse(pattern, flags)` qui produit un arbre syntaxique interne
   - Si le parsing echoue (`re.error`), retourne `None` — signalant une regex invalide
   - **Extraction des clauses** via `_subpattern_clauses(parsed, ...)`

#### Resultat : `RegexQueryPlan`

```python
@dataclass(slots=True)
class RegexQueryPlan:
    is_regex: bool          # True si regex detectee
    pattern: str            # Le pattern regex brut
    flags: int              | Flags compiles (OR bit a bit)
    clauses: list[set[str]] # Clauses trigrammes pour prefiltrage
```

#### Parametres de securite

| Parametre | Defaut | Role |
|-----------|--------|------|
| `max_clauses` | 64 | Nombre maximum de clauses (evite l'explosion combinatoire) |
| `max_clause_trigrams` | 32 | Nombre maximum de trigrammes par clause |

Ces limites empechent les attaques par regex pathological (ReDoS) et les explosions de memoire sur les regex complexes.

---

## 2. Extraction des clauses trigrammes — `_subpattern_clauses`

### 2.1 Principe

La fonction `_subpattern_clauses` parcourt l'arbre syntaxique `sre_parse` et extrait les sequences de **litteraux obligatoires**. Ces sequences sont converties en trigrammes pour former des **clauses de prefiltrage**.

L'idee centrale : une clause trigramme represente un ensemble de trigrammes qui doivent **tous** etre presents dans un document pour que la regex puisse matcher. Une regex peut produire **plusieurs clauses** (branches d'alternatives), et un document est candidat s'il satisfait **au moins une** clause.

### 2.2 Machine a etats

L'algorithme maintient une liste d'etats. Chaque etat est un couple :

```python
states: list[tuple[set[str], str]]
#        required_trigrams  literal_tail
```

- `required_trigrams` : ensemble des trigrammes obligatoires accumules
- `literal_tail` : chaine de caracteres litteraux en cours d'accumulation (pas encore convertie en trigrammes)

### 2.3 Traitement des operations sre_parse

#### `LITERAL` — Caractere litteral

```python
if op == sre_constants.LITERAL:
    ch = chr(arg)
    states = [(required, tail + ch) for required, tail in states]
```

Le caractere est ajoute au `literal_tail` de chaque etat. Aucun trigramme n'est encore genere — on attend de savoir si la sequence litterale continue.

**Exemple** : Pour `"art"`, les trois LITERAL consecutifs accumulent `tail = "a"`, puis `"ar"`, puis `"art"`.

#### `SUBPATTERN` — Groupe capture `( ... )`

```python
if op == sre_constants.SUBPATTERN:
    _, _, _, nested = arg
    nested_clauses = _subpattern_clauses(nested, ...)
    next_states = []
    for required, tail in states:
        flushed_required, _ = _flush_tail(required, tail, ...)
        for clause in nested_clauses or [set()]:
            merged = set(flushed_required)
            merged.update(clause)
            next_states.append((merged, ""))
    states = next_states
    states = _dedupe_state(states, ...)
```

**Comportement** :
1. Le `literal_tail` courant est converti en trigrammes (`_flush_tail`)
2. L'algorithme recurse dans le sous-pattern
3. Pour chaque clause du sous-pattern, on fusionne les trigrammes
4. Si le sous-pattern ne produit aucune clause (regex pure sans litteraux), on utilise `[set()]` (clause vide = pas de contrainte)

#### `BRANCH` — Alternative `a|b`

```python
if op == sre_constants.BRANCH:
    _, branches = arg
    branch_clauses = []
    for branch in branches:
        branch_clauses.extend(_subpattern_clauses(branch, ...))
    branch_clauses = _dedupe_clauses(branch_clauses, ...)
    next_states = []
    for required, tail in states:
        flushed_required, _ = _flush_tail(required, tail, ...)
        for clause in branch_clauses or [set()]:
            merged = set(flushed_required)
            merged.update(clause)
            next_states.append((merged, ""))
    states = _dedupe_state(next_states, ...)
```

**Comportement** :
1. Chaque branche est analysee independamment
2. Les clauses de toutes les branches sont collectees (produit cartesien avec les etats existants)
3. Deduplication pour eviter les etats redondants

**Exemple** : `article|loi` produit deux clauses :
- Clause 1 : trigrammes de `"article"` = `{"art", "rti", "tic", "icl", "cle"}`
- Clause 2 : trigrammes de `"loi"` = `{"loi"}` (texte court, trigramme unique si longueur >= 3, sinon ensemble contenant le texte)

#### `MAX_REPEAT` / `MIN_REPEAT` — Quantifieurs `*`, `+`, `?`, `{n,m}`

```python
if op in (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT):
    min_repeat, _, nested = arg
    if min_repeat <= 0:
        # Partie optionnelle : pas de contrainte trigramme obligatoire
        states = [_flush_tail(required, tail, ...) for required, tail in states]
    else:
        # min_repeat >= 1 : le contenu est obligatoire
        nested_clauses = _subpattern_clauses(nested, ...)
        # ... fusion identique a SUBPATTERN
```

**Comportement critique** :
- Si `min_repeat == 0` (ex: `*`, `?`, `{0,}`) : le contenu est **optionnel**. Le `literal_tail` est converti, mais **aucun trigramme** du contenu optionnel n'est ajoute. Cela garantit la correction : un document ne contenant pas la partie optionnelle ne doit pas etre elimine par le prefiltrage.
- Si `min_repeat >= 1` (ex: `+`, `{2,}`, `{1,5}`) : le contenu apparait au moins une fois, donc ses trigrammes sont obligatoires.

#### Autres operations — Rupture de sequence

```python
# Tout ce qui n'est pas LITERAL, SUBPATTERN, BRANCH, ou REPEAT
states = [_flush_tail(required, tail, ...) for required, tail in states]
```

Les operations comme `AT` (`^`, `$`), `ANY` (`.`), `IN` (`[...]`), `NOT_LITERAL`, `GROUPREF` (`\1`), etc. sont traitees comme des **ruptures de sequence litterale**. Le `literal_tail` est converti en trigrammes, mais l'operation elle-meme n'ajoute aucune contrainte.

### 2.4 Flush du tail — `_flush_tail`

```python
def _flush_tail(required: set[str], literal_tail: str, max_clause_trigrams: int) -> tuple[set[str], str]:
    if literal_tail:
        required = set(required)
        required.update(trigrams(literal_tail))
        if len(required) > max_clause_trigrams:
            required = set(sorted(required)[:max_clause_trigrams])
    return required, ""
```

- Convertit le `literal_tail` accumule en trigrammes
- Les ajoute a l'ensemble `required`
- Si le nombre de trigrammes depasse `max_clause_trigrams`, on garde les N premiers (tri stable)
- Retourne `(required_actualise, "")`

### 2.5 Deduplication — `_dedupe_clauses` et `_dedupe_state`

Deux fonctions de deduplication empechent l'explosion combinatoire :

**`_dedupe_clauses`** : elimine les clauses identiques (meme ensemble de trigrammes) et limite a `max_clauses`.

**`_dedupe_state`** : elimine les etats identiques (meme `required` + meme `tail`) et limite a `max_clauses`.

### 2.6 Exemples concrets d'extraction

#### Exemple 1 : `/article\s+3/`

```
Pattern: article\s+3
sre_parse: [LITERAL 'a', LITERAL 'r', LITERAL 't', ..., LITERAL 'e',  IN [\s]+, LITERAL '3']

Traitement :
1. LITTERAUX "article" -> tail = "article"
2. IN [\s]+ -> flush("article") -> required = trigrams("article") = {"art","rti","tic","icl","cle"}
3. LITTERAUX "3" -> tail = "3"

Resultat : clauses = [{"art","rti","tic","icl","cle"}]
```

#### Exemple 2 : `/article|loi/`

```
Pattern: article|loi
sre_parse: BRANCH(article, loi)

Traitement :
1. Branche "article" -> clauses = [{"art","rti","tic","icl","cle"}]
2. Branche "loi" -> clauses = [{"loi"}]

Resultat : clauses = [{"art","rti","tic","icl","cle"}, {"loi"}]
```

Un document est candidat s'il contient les trigrammes de "article" **OU** les trigrammes de "loi".

#### Exemple 3 : `/art.*icle/`

```
Pattern: art.*icle
sre_parse: [LITERAL 'a', LITERAL 'r', LITERAL 't', MAX_REPEAT(0, MAX, ANY), LITERAL 'i', LITERAL 'c', LITERAL 'l', LITERAL 'e']

Traitement :
1. LITTERAUX "art" -> tail = "art"
2. MAX_REPEAT(min=0) -> flush("art") -> required = {"art"}
3. LITTERAUX "icle" -> tail = "icle"

Resultat : clauses = [{"art"}]
```

Note : Seuls les trigrammes de `"art"` sont extraits car `.*` est optionnel et `"icle"` n'est pas flush a la fin... En fait, le flush final convertit `"icle"` en trigrammes. Donc :

```
Resultat reel : clauses = [{"art", "icl", "cle"}]
```

#### Exemple 4 : `/r.gemment/i`

```
Pattern: r.gemment
Flags: IGNORECASE

Traitement :
1. LITERAL 'r' -> tail = "r"
2. ANY '.' -> flush("r") -> required = {"r"} (trop court pour trigramme, ensemble = {"r"})
3. LITTERAUX "gemment" -> tail = "gemment"

Resultat : clauses = [{"r", "gem", "emm", "mme", "men", "ent"}]
```

---

## 3. L'optimisation par trigrammes (prefiltrage)

### 3.1 Pourquoi le prefiltrage n'est pas utilise dans rg_search

Contrairement a la strategie **lexical** (methode `_search_regex` dans `CursorLikeIndex`) qui utilise les clauses trigrammes pour prefiltrer les candidats, la strategie **rg** (`rg_search`) **ignore completement les clauses trigrammes** pour le scan. Elle effectue un scan lineaire de tous les documents.

Cependant, le `build_regex_query_plan` est quand meme appele dans `rg_search` pour **detecter si la requete est une regex** et **compiler le pattern**. Les clauses trigrammes sont calculees mais non utilisees pour le filtrage.

### 3.2 Le prefiltrage dans la strategie lexicale (pour comparaison)

Dans la methode `_search_regex` (appelee par `CursorLikeIndex.search()` pour la strategie lexicale), les clauses trigrammes servent a reduire le nombre de documents a scanner :

```python
candidates = self.trigram.candidates_from_clauses(trigram_clauses)
if not candidates:
    candidates = set(self.trigram.doc_ids)  # fallback : tous les docs
```

La methode `candidates_from_clauses` :

```python
def candidates_from_clauses(self, clauses: list[set[str]]) -> set[str]:
    union_docs: set[str] = set()
    for clause in clauses:
        if not clause:
            union_docs |= self.doc_ids  # clause vide = tous les docs
            continue
        union_docs |= self.candidates_for_all_trigrams(clause)
    return union_docs
```

**Logique** : Union des candidats de chaque clause (OU entre branches), intersection des trigrammes au sein d'une clause (ET entre trigrammes d'une meme branche).

### 3.3 Tableau comparatif prefiltrage

| Aspect | Strategie lexicale (`_search_regex`) | Strategie rg (`rg_search`) |
|--------|--------------------------------------|---------------------------|
| Appel `build_regex_query_plan` | Oui | Oui |
| Utilisation des clauses | Prefiltrage via `candidates_from_clauses` | Non (ignores) |
| Documents scannes | Candidats trigrammes uniquement | **Tous** les documents |
| Erreur regex | Fallback vers recherche lexicale standard | Fallback vers recherche token |
| Verfication regex | `compiled.search(text)` (premier match) | `compiled.finditer(text)` (tous les matches) |

---

## 4. Formules de scoring

### 4.1 Chemin regex — Match d'expression reguliere

Quand la requete est detectee comme regex valide et compilee avec succes :

```python
compiled = re.compile(plan.pattern, plan.flags)
matches = list(compiled.finditer(text))
if not matches:
    continue  # Document elimine

total_match_len = sum(max(1, m.end() - m.start()) for m in matches)
score = min(1.0, 0.5 + (0.5 * (total_match_len / max(1, len(text)))))
```

**Decomposition** :

```
score = min(1.0, 0.5 + 0.5 * densite_match)

ou densite_match = total_match_len / len(text)
```

| Composante | Formule | Plage |
|------------|---------|-------|
| Base | `0.5` | Fixe |
| Bonus densite | `0.5 * (total_match_len / len(text))` | [0.0, 0.5] |
| Score final | `min(1.0, base + bonus)` | [0.5, 1.0] |

**Plafond a 0.5** : Un match regex, meme trivial, ne peut jamais avoir un score inferieur a 0.5. Cela garantit qu'un match regex est **toujours** mieux classe qu'un match token-only.

**Plafond a 1.0** : Le score ne depasse jamais 1.0.

**Exemples numeriques** :

| Scenario | Texte | Match | total_match_len | Score |
|----------|-------|-------|-----------------|-------|
| Match court, texte long | 1000 chars | `"art"` a pos 50 | 3 | `min(1.0, 0.5 + 0.5*3/1000)` = 0.5015 |
| Match moyen | 200 chars | `"article 42"` a pos 80 | 10 | `min(1.0, 0.5 + 0.5*10/200)` = 0.525 |
| Multiple matches | 500 chars | 3 matches de 20 chars chacun | 60 | `min(1.0, 0.5 + 0.5*60/500)` = 0.56 |
| Couverture elevee | 100 chars | Match de 80 chars | 80 | `min(1.0, 0.5 + 0.5*80/100)` = 0.9 |
| Couverture totale | 50 chars | Match de 50 chars | 50 | `min(1.0, 0.5 + 0.5*50/50)` = 1.0 |

### 4.2 Chemin fallback — Recherche tokenisee

Quand la requete n'est pas une regex ou que la compilation echoue :

```python
q_tokens = _tokenize(query)
if not q_tokens:
    continue  # Requete vide

text_norm = _normalize_text(text)
hit_tokens = sum(1 for token in q_tokens if token in text_norm)
if hit_tokens == 0:
    continue  # Aucun token trouve

score = hit_tokens / len(q_tokens)
```

**Formule** :

```
score = tokens_trouves / tokens_requete
```

| Composante | Plage |
|------------|-------|
| `hit_tokens` | [0, len(q_tokens)] |
| Score | [0.0, 1.0] |

**Exemples numeriques** :

| Requete | Tokens requete | Texte normalise | Tokens trouves | Score |
|---------|----------------|-----------------|----------------|-------|
| `"article loi"` | `["article", "loi"]` | `"l'article 3 de la loi..."` | 1 (loi) | 0.5 |
| `"article 42"` | `["article", "42"]` | `"voir article 42 du code"` | 2 | 1.0 |
| `"reglement"` | `["reglement"]` | `"le reglement interieur"` | 1 | 1.0 |
| `"xyz abc"` | `["xyz", "abc"]` | `"aucun rapport"` | 0 | elimine |

### 4.3 Comparaison des scores entre strategies

| Strategie | Formule | Plage typique | Garantie minimale |
|-----------|---------|---------------|-------------------|
| RG (regex match) | `min(1.0, 0.5 + 0.5 * densite)` | [0.5, 1.0] | 0.5 |
| RG (token fallback) | `hit_tokens / total_tokens` | [0.0, 1.0] | Aucune |
| Lexicale (regex verifie) | `min(1.0, 0.7 + 0.3 * densite)` | [0.7, 1.0] | 0.7 |
| Lexicale (standard) | `0.55*t + 0.35*k + 0.10*p` | [0.0, 1.0] | Aucune |

La strategie lexicale attribue un score plancher plus eleve (0.7) aux matches regex verifies car elle combine prefiltrage trigramme + verification regex, donc les faux positifs sont tres improbables.

---

## 5. Flux d'execution complet

### Etape 1 — Reception de la requete

```python
# pipeline.py
async def run(self, query, index_name="default", top_k=10, strategy="hybrid"):
    ...
    if strategy == "rg":
        lexical_results = self.registry.rg_search(
            index_name=index_name,
            query=query,
            top_k=top_k,
        )
        ...
    # Les resultats rg sont directement les ranked_results
    if strategy == "rg":
        ranked_results = lexical_results
```

**Point cle** : La strategie "rg" ne passe **jamais** par `fuse_search_results`. Pas de fusion semantique, pas de normalisation, pas de ponderation. Les scores bruts sont directement tries.

### Etape 2 — Delegation au registre

```python
# local_registry.py
def rg_search(self, index_name: str, query: str, top_k: int = 10) -> list[dict]:
    return self._indexes[index_name].rg_search(query=query, top_k=top_k)
```

Chaque `index_name` a son propre `CursorLikeIndex`. Le registre ne fait que deleguer.

### Etape 3 — Analyse de la requete

```python
# cursor_like.py - rg_search()
plan = build_regex_query_plan(query)
is_regex = bool(plan and plan.is_regex)
```

Trois resultats possibles :

| Resultat de `plan` | `is_regex` | Comportement |
|---------------------|------------|-------------|
| `None` | `False` | Regex invalide -> fallback token |
| `RegexQueryPlan(is_regex=False, ...)` | `False` | Texte simple -> fallback token |
| `RegexQueryPlan(is_regex=True, ...)` | `True` | Regex valide -> compilation |

### Etape 4 — Compilation regex

```python
compiled: re.Pattern[str] | None = None
if is_regex and plan:
    try:
        compiled = re.compile(plan.pattern, plan.flags)
    except re.error:
        compiled = None  # Fallback vers token
```

**Double securite** : Meme si `sre_parse` a reussi, la compilation peut echouer. Dans ce cas, `compiled` reste `None` et le chemin token est emprunte.

### Etape 5 — Scan complet des documents

```python
for doc_id, doc in self.documents.items():
    text = str(doc.get("text", ""))
    if not text:
        continue  # Document vide ignore

    if compiled is not None:
        # Chemin regex
        matches = list(compiled.finditer(text))
        if not matches:
            continue
        total_match_len = sum(max(1, m.end() - m.start()) for m in matches)
        score = min(1.0, 0.5 + (0.5 * (total_match_len / max(1, len(text)))))
    else:
        # Chemin token fallback
        q_tokens = _tokenize(query)
        text_norm = _normalize_text(text)
        hit_tokens = sum(1 for token in q_tokens if token in text_norm)
        if hit_tokens == 0:
            continue
        score = hit_tokens / len(q_tokens)
```

**Difference avec `finditer` vs `search`** :
- `rg_search` utilise `finditer` (tous les matches) pour calculer `total_match_len`
- `_search_regex` (lexical) utilise `search` (premier match uniquement) pour un score plus simple

### Etape 6 — Construction des resultats

```python
results.append({
    "id": doc_id,
    "score": round(float(score), 6),
    "text": text,
    "metadata": doc.get("metadata", {}),
    "source": "rg",
})
```

Le champ `"source": "rg"` identifie les resultats dans les benchmarks et la fusion.

### Etape 7 — Tri et selection

```python
results.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
return results[:top_k]
```

Tri decroissant par score, puis troncature a `top_k`.

---

## 6. Gestion des erreurs

### 6.1 Regex invalide

```python
# Dans build_regex_query_plan
try:
    parsed = sre_parse.parse(pattern, flags)
except re.error:
    return None  # Signal d'echec
```

```python
# Dans rg_search
plan = build_regex_query_plan(query)
is_regex = bool(plan and plan.is_regex)  # None -> False
```

**Consequence** : Une regex invalide bascule silencieusement vers le chemin token fallback. Pas d'exception, pas de crash.

### 6.2 Compilation echouee

```python
if is_regex and plan:
    try:
        compiled = re.compile(plan.pattern, plan.flags)
    except re.error:
        compiled = None
```

**Double protection** : Le parsing `sre_parse` peut reussir mais la compilation `re.compile` echouer (ex: lookbehind a largeur variable en Python). Dans ce cas, fallback vers tokens.

### 6.3 Requete vide

```python
if not query.strip():
    return []
```

Retour immediat sans erreur.

### 6.4 Document sans texte

```python
text = str(doc.get("text", ""))
if not text:
    continue
```

Documents vides silencieusement ignores.

### 6.5 Tokens vides en fallback

```python
q_tokens = _tokenize(query)
if not q_tokens:
    continue
```

Si la requete ne contient que des caracteres speciaux non tokenisables, le document est ignore.

---

## 7. Evaluation de la strategie rg

### 7.1 Dans `EvaluationRunner`

```python
# runner.py
async def evaluate_search(self, samples, corpus, strategy="baseline", top_k=10):
    if strategy == "baseline":
        results = self.baseline_retriever.search(...)
    else:
        run = await self.search_pipeline.run(
            query=sample.query,
            index_name=sample.index_name,
            top_k=top_k,
            strategy=strategy,  # "rg" passe ici
        )
        results = run["results"]
```

La strategie "rg" utilise le meme chemin que "lexical" et "semantic" via `SearchPipeline.run`, garantissant des conditions d'evaluation identiques.

### 7.2 Comparaison multi-strategies

```python
async def evaluate_search_strategies(self, samples, corpus, strategies=None, top_k=10):
    selected = strategies or ["baseline", "lexical", "semantic", "hybrid", "rg"]
    for strategy in selected:
        reports[strategy] = await self.evaluate_search(...)
```

Par defaut, **cinq strategies** sont comparees : baseline, lexical, semantic, hybrid, rg.

### 7.3 Metriques collectees

| Metrique | Description |
|----------|-------------|
| `recall_at_k` | Proportion de documents pertinents retrouves dans les top_k |
| `mrr` | Mean Reciprocal Rank — position du premier document pertinent |
| `ndcg_at_k` | Normalized Discounted Cumulative Gain |
| `latency_ms` | Temps de reponse en millisecondes |
| `candidate_count` | Nombre de candidats avant filtrage |
| `candidate_kept_count` | Nombre de resultats retournes |
| `gold_present` | Au moins un document pertinent dans les resultats |
| `best_relevant_rank` | Rang du meilleur document pertinent |

### 7.4 Benchmark `run_find_experiment`

```python
selected = strategies or ["baseline", "lexical", "semantic", "hybrid", "rg"]
needs_index = any(s != "baseline" for s in selected)
if needs_index:
    await self._index_experiment_corpus(corpus, index_name)
```

La strategie rg necessite l'indexation du corpus (comme lexical et semantic) car elle opere sur le `CursorLikeIndex` en memoire. Seul le baseline n'a pas besoin d'index.

---

## 8. Comparaison avec les autres strategies

| Critere | RG | Lexical | Semantic | Hybrid |
|---------|-----|---------|----------|--------|
| **Service externe** | Non | Non | NextPlaid | NextPlaid |
| **GPU requis** | Non | Non | Oui | Oui |
| **Temps de reponse** | ~1-10 ms | ~1-5 ms | ~50-200 ms | ~50-200 ms |
| **Scan complet** | Oui (tous les docs) | Non (prefiltrage) | Non (embeddings) | Non |
| **Prefiltrage trigrammes** | Non | Oui | Non | Partiel |
| **Correspondance exacte** | Oui (regex) | Oui (regex + trigrammes) | Non | Oui |
| **Fautes de frappe** | Non | Partiel (trigrammes) | Oui | Oui |
| **Synonymes** | Non | Non | Oui | Oui |
| **Regex natif** | Oui | Via planificateur | Non | Via planificateur |
| **Deterministe** | Oui | Oui | Non | Non |
| **Score plancher regex** | 0.5 | 0.7 | N/A | Variable |
| **Source resultats** | `"rg"` | `"lexical"` | Variable | `"semantic"` + `"lexical"` |
| **Utilisation principale** | Baseline evaluation | Recherche rapide | Recherche semantique | Meilleur des deux |

### Positionnement de rg dans la pipeline

```
Qualite des resultats (typique) :

  Hybrid > Semantic > Lexical > RG > Baseline

Latence (typique) :

  RG ~ Lexical << Hybrid ~ Semantic

Determinisme :

  RG = Lexical = Baseline (deterministes)
  Hybrid ~ Semantic (non deterministes, depend du modele)
```

---

## 9. Points forts et limites

### Points forts

- **Simplicite maximale** : Scan lineaire, pas d'index a maintenir, pas d'heuristique
- **Determinisme complet** : Memes requetes, memes resultats, a chaque execution
- **Support regex natif** : Expressions regulieres completement supportees via `re.compile`
- **Baseline solide** : Fournit le plancher de reference pour les benchmarks d'evaluation
- **Zero dependance** : Pas de service externe, pas de GPU, pas de modele
- **Robustesse** : Fallback gracieux vers recherche token si la regex echoue
- **Couverture complete** : Scan de tous les documents, aucun risque de faux negatif du au prefiltrage

### Limites

- **Pas de prefiltrage** : Scan de tous les documents a chaque requete (O(n)) — ne scale pas avec le volume
- **Pas de comprehension semantique** : "voiture" ne matche pas "automobile"
- **Pas de stemming** : "reglement" ne matche pas "reglements"
- **Scoring grossier** : Base uniquement sur la densite du match, pas sur la pertinence contextuelle
- **Pas d'index persistant** : Les structures existent en memoire mais ne sont pas utilisees pour le prefiltrage
- **Pas de support des fautes de frappe** : Contrairement au trigramme lexical qui tolere les erreurs partielles
- **Performance en O(n)** : Le temps de reponse croit lineairement avec le nombre de documents
- **Tokens en fallback** : La recherche tokenisee utilise `in` sur le texte normalise, pas l'index inverse

---

## 10. Diagramme de decision complet

```
rg_search(query)
  |
  v
query vide ? ──Oui──> return []
  |
  Non
  v
build_regex_query_plan(query)
  |
  +──> plan = None (regex invalide) ──> is_regex = False
  +──> plan.is_regex = False ─────────> is_regex = False
  +──> plan.is_regex = True ──────────> is_regex = True
                                          |
                                          v
                                    re.compile(pattern, flags)
                                          |
                                     +────────+
                                     | Erreur |
                                     +────────+
                                          |
                                    compiled = None ──> is_regex = False (de facto)
                                          |
                                    compiled = Pattern OK

  Pour CHAQUE document :
  |
  +── text vide ? ──> skip
  |
  +── compiled != None :
  |     finditer(text) -> matches
  |     pas de match ? ──> skip
  |     score = min(1.0, 0.5 + 0.5 * total_match_len / len(text))
  |
  +── compiled == None :
        _tokenize(query) -> q_tokens
        tokens vides ? ──> skip
        hit_tokens = nombre de tokens trouves dans le texte
        hit_tokens == 0 ? ──> skip
        score = hit_tokens / len(q_tokens)

  Tri par score decroissant
  return top_k resultats (source: "rg")
```
