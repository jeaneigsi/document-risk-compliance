# Scenarios d'Utilisation de l'Application

Ce document decrit l'etat reel de l'application au 26 mars 2026.

Il distingue:
- ce qui est deja implemente,
- ce qui est recommande en usage,
- ce qui reste une cible d'architecture dans [architetcure.md](/home/jean/projects/doctorat/projet-1/docs-regex/architetcure.md).

## 1. Vue d'ensemble

L'application couvre aujourd'hui 5 surfaces principales:

1. Ingestion documentaire: upload, OCR, extraction, stockage, suppression.
2. Recherche de preuves: `lexical`, `semantic`, `hybrid`, `rg`.
3. Detection d'incoherences: pipeline deterministe avec appel LLM conditionnel.
4. Analyse LLM sur document: retrieval + LLM sur preuves.
5. Experimentation scientifique: benchmarks, comparaison de strategies, historique SQLite, lecture detaillee des samples.

## 2. Prerequis d'execution

## 2.1 Services requis

- API FastAPI: `http://localhost:8000`
- Frontend Vue/Vuetify
- Worker Celery
- Redis
- MinIO
- OCR provider
- NextPlaid: `http://localhost:8081`

Note:
- le port `8081` pour NextPlaid est volontaire dans ce projet.
- il ne doit pas etre traite comme une incoherence de configuration.

## 2.2 Variables importantes

- `NEXT_PLAID_URL=http://localhost:8081`
- `OPENROUTER_API_KEY=...`
- `OCR_API_KEY=...`
- `HF_TOKEN=...` ou `HUGGINGFACE_HUB_TOKEN=...`
- `HF_HOME` / `HF_DATASETS_CACHE` si tu veux maitriser le cache local datasets
- `SEARCH_AUTO_INDEX=true` si tu veux l'indexation automatique apres extraction

## 2.3 Base URL

Pour le backend:

- `http://localhost:8000/api/v1`

Exemples:

- sante: `GET http://localhost:8000/api/v1/health`
- upload: `POST http://localhost:8000/api/v1/documents/upload`
- recherche: `POST http://localhost:8000/api/v1/search`
- experiences: `POST http://localhost:8000/api/v1/eval/experiments/find`

## 3. Ingestion documentaire

## 3.1 Workflow standard

Objectif: charger un PDF/image, attendre l'extraction, puis exploiter le document.

Etapes:

1. `POST /api/v1/documents/upload`
2. `GET /api/v1/documents/{id}/status`
3. `GET /api/v1/documents/{id}/content`
4. facultatif: `POST /api/v1/documents/{id}/extract/retry`
5. facultatif: `POST /api/v1/documents/{id}/index/retry`

Statuts document:

- `pending`
- `processing`
- `completed`
- `failed`

Le statut detaille expose maintenant aussi:

- `index_status`
- `indexed_count`
- `details`

## 3.2 Ce qui se passe apres upload

Quand un document est charge:

1. le fichier est stocke,
2. l'OCR extrait le contenu,
3. le backend produit un `markdown`,
4. des `evidence_units` sont construites,
5. ces `evidence_units` peuvent etre indexees automatiquement.

Important:

- un document peut etre `completed` sur le plan extraction tout en ayant un `index_status` different de `completed`
- il faut donc regarder le statut d'indexation, pas seulement le statut OCR

## 3.3 Construction des `evidence_units`

Le chunking actuel n'est pas un chunking LLM a fenetre glissante.

Le projet utilise un chunking structurel:

1. priorite aux blocs OCR/layout,
2. un `evidence_unit` par bloc,
3. ajout de blocs markdown manquants quand le layout OCR est partiel,
4. fallback vers un bloc markdown unique si aucun bloc n'a pu etre produit.

Structure utile d'un `evidence_unit`:

- `evidence_id`
- `document_id`
- `content`
- `source_type`
- `page_number`
- `metadata`

Cela veut dire que l'index est alimente par blocs documentaires exploitables, pas par tokens arbitraires.

Important:

- la construction des `evidence_units` n'est plus limitee au layout pur
- si le markdown contient des passages absents du layout, ils peuvent maintenant etre ajoutes comme `markdown_block`

## 4. Recherche de preuves

## 4.1 Endpoint principal

- `POST /api/v1/search`

Payload type:

```json
{
  "query": "budget 1200 EUR",
  "index_name": "default",
  "top_k": 10,
  "strategy": "hybrid"
}
```

## 4.2 Strategies implementees

Le projet supporte actuellement 5 strategies comparables en experimentation, dont 4 exposees comme vraies strategies de recherche produit.

### 4.2.1 `lexical`

Role:
- recherche locale inspiree Cursor-like.

Implementation actuelle:
- index trigram local en memoire,
- inverted index,
- support regex,
- planner regex par clauses,
- verification finale par `re.search` pour garantir l'exactitude du match.

Quand l'utiliser:
- patterns precis,
- regex,
- recherche lexicale rapide,
- candidate generation economique.

### 4.2.2 `rg`

Role:
- full scan local regex/texte.

Implementation actuelle:
- parcours de tout l'index local,
- verification regex/textuelle directe,
- utile comme reference robuste sur petit ou moyen corpus.

Quand l'utiliser:
- comparer la robustesse d'un regex,
- valider qu'un match n'a pas ete perdu par le prefiltrage lexical.

### 4.2.3 `semantic`

Role:
- recherche semantique via NextPlaid.

Implementation actuelle:
- creation d'index explicite,
- ajout documents avec encodage serveur,
- recherche via `search_with_encoding`,
- support de filtres metadata,
- fallback legacy si besoin.

Modele reel utilise cote moteur NextPlaid:

- `lightonai/answerai-colbert-small-v1-onnx`

Important:
- `semantic` est oriente late interaction via NextPlaid/ColBERT.
- l'application globale n'est pas "100% late interaction" car `lexical`, `rg` et `baseline` ne le sont pas.

### 4.2.4 `hybrid`

Role:
- fusion de `semantic` et `lexical`.

Implementation actuelle:
- pool semantique interne plus large que `top_k`,
- fusion score + rang,
- meilleur compromis theorique qualite/rappel.

Important:
- `hybrid` n'est pas encore une vraie cascade `lexical -> semantic rerank`.
- c'est une fusion de resultats, pas encore le design final cible de [architetcure.md](/home/jean/projects/doctorat/projet-1/docs-regex/architetcure.md).

### 4.2.5 `baseline`

Role:
- baseline scientifique uniquement.

Implementation actuelle:
- retriever lexical simple sur corpus d'evaluation.

Important:
- `baseline` n'est pas un oracle.
- il ne faut pas le confondre avec une verite terrain.
- en revanche, il ne doit pas etre utilise comme strategie produit normale sur `/search`.

## 4.3 Quel index choisir

L'index logique passe par `index_name`.

Cas principaux:

1. `default`
- index general de travail.

2. index documentaires ou experimentaux dedies
- ex: `contracts`, `evidence`, `find-benchmark`

Ce nom sert a:
- separer plusieurs corpus,
- lancer des experiences sans polluer l'index principal,
- comparer plusieurs strategies sur le meme espace documentaire.

## 4.4 Que se passe-t-il quand on alimente un index

Lors de l'indexation:

1. le backend alimente l'index local `lexical/rg`,
2. il alimente aussi NextPlaid pour `semantic`,
3. l'index logique est partage par les strategies qui savent l'exploiter.

Consequence:
- si tu veux comparer `lexical`, `semantic`, `hybrid`, `rg` sur un meme corpus, il faut utiliser le meme `index_name`.

Important:

- `semantic` repose sur NextPlaid, qui est partage entre processus
- `lexical` et `rg` reposent encore sur un index local en memoire
- donc une auto-indexation effectuee dans le worker ne garantit pas a elle seule que `lexical` / `rg` seront immediatement visibles depuis le process API
- c'est pour cela qu'une relance d'indexation explicite existe maintenant cote API

## 4.5 Relance d'indexation

Endpoint:

- `POST /api/v1/documents/{id}/index/retry`

Usage:

1. le document est deja extrait,
2. on reconstruit les `evidence_units`,
3. on reindexe dans l'index logique demande,
4. on remet a jour `index_status` et `indexed_count`.

Quand l'utiliser:

- si l'auto-indexation a echoue,
- si `LLM Analyze` ne semble utiliser aucune evidence,
- si tu veux recharger l'index API apres un redemarrage,
- si tu veux forcer une reindexation propre d'un document.

## 5. Detection d'incoherences

## 5.1 Endpoint

- `POST /api/v1/detect`

Payload type:

```json
{
  "document_id": "uuid",
  "claims": [
    "Le budget approuve est de 1200 EUR"
  ]
}
```

## 5.2 Etat reel du pipeline detect

Point important:

Le pipeline `/detect` actuel n'utilise pas encore `lexical`, `semantic`, `hybrid` ou `rg`.

Il fonctionne aujourd'hui ainsi:

1. lecture du markdown extrait,
2. split en snippets,
3. contexte rapide local,
4. detecteurs deterministes,
5. comparateurs structurels,
6. LLM uniquement si la severite est suffisamment elevee.

Donc:

- oui, la detection actuelle est majoritairement regex/heuristique,
- non, elle n'est pas encore alignee sur l'architecture cible "retrieval-driven" du document d'architecture.

## 5.3 Ce que fait la detection aujourd'hui

Le pipeline cherche surtout:

- conflits de dates,
- conflits de montants,
- conflits de references,
- divergences textuelles simples,
- incoherences structurelles elementaires.

Il est utile pour:

- verifier rapidement des claims simples,
- avoir un premier filtre peu couteux,
- decider si un appel LLM est necessaire.

Il est moins adapte, en l'etat, a:

- contradictions semantiques fines,
- incoherences necessitant une vraie recherche de preuves dans l'index,
- comparaisons multi-documents riches.

## 6. Analyse LLM sur document

## 6.1 Endpoint recommande

- `POST /api/v1/llm/analyze/document`

Payload type:

```json
{
  "document_id": "uuid",
  "claim": "Le budget approuve est de 1200 EUR",
  "strategy": "hybrid",
  "index_name": "default",
  "top_k": 5,
  "model": "openrouter/qwen/qwen3.5-9b:exacto"
}
```

## 6.2 Strategie par defaut

Par defaut, l'analyse LLM sur document utilise:

- `strategy = "hybrid"`

Ce flux est aujourd'hui le plus coherent pour un usage entreprise ou power user:

1. recuperer des preuves,
2. montrer les preuves,
3. demander au LLM de raisonner sur ces preuves.

## 6.2.1 Resilience actuelle du retrieval dans `LLM Analyze`

Le endpoint `POST /api/v1/llm/analyze/document` ne depend plus uniquement d'un index prealablement pret.

Flux reel:

1. tentative de recherche normale dans l'index demande,
2. si aucun resultat, reindexation du document dans le process API,
3. nouvelle tentative de recherche,
4. si toujours aucun resultat, fallback local sur les `evidence_units` du document lui-meme.

Consequence:

- si un document contient des passages utiles, le LLM a maintenant beaucoup plus de chances de recevoir de vraies evidence
- les evidence retournees exposent un `metadata.retrieval_mode` pour indiquer le chemin utilise

Valeurs utiles de `retrieval_mode`:

- `indexed`
- `indexed_after_reindex`
- `document_local_fallback:baseline`

## 6.3 Pourquoi ce flux est meilleur que `POST /llm/analyze`

`POST /api/v1/llm/analyze`:
- utile pour debug modele/prompt,
- ne doit pas etre le flux principal produit.

`POST /api/v1/llm/analyze/document`:
- raisonne sur un document reel,
- garde des evidences tracees,
- permet de comparer strategies et qualite de contexte,
- correspond mieux au besoin metier.

Si `evidence_count = 0` sur un document riche, il faut verifier en priorite:

1. `index_name`
2. `index_status`
3. la necessite de relancer `index/retry`
4. la qualite reelle de l'extraction OCR

## 6.4 Cout LLM

Point important:

Les experiences de retrieval n'appellent pas forcement le LLM.

Donc dans l'historique d'experimentation:
- les couts LLM peuvent etre nuls,
- ce n'est pas un bug si aucune etape LLM n'est dans la run.

Pour la couche cout:
- LiteLLM suffit pour usage/tokens/cout par appel,
- les metriques IR restent calculees cote projet.

## 7. Experimentation scientifique

## 7.1 Endpoint principal

- `POST /api/v1/eval/experiments/find`

Malgre le nom historique, cet endpoint supporte maintenant plusieurs benchmarks.

## 7.2 Datasets supportes

### 7.2.1 `kensho/FIND`

Role:
- benchmark principal oriente incoherences et preuves.

Points importants:
- dataset gated,
- il faut accepter les conditions sur Hugging Face,
- il faut fournir `HF_TOKEN` ou `HUGGINGFACE_HUB_TOKEN`.

Splits utilises dans l'application:
- `validation`
- `test`

Important:
- `train` n'est pas le split a utiliser ici.

### 7.2.2 `ibm-research/Wikipedia_contradict_benchmark`

Role:
- deuxieme benchmark pour tester des contradictions plus semantiques.

Interet:
- il complete FIND,
- il reduit le biais "trop lexical",
- il aide a juger si `semantic` ou `hybrid` apportent vraiment quelque chose.

Important:

- dans le protocole actuel, on n'utilise pas l'article Wikipedia complet via `url`
- on utilise seulement les champs deja presents dans le dataset:
  - `question`
  - `context1`
  - `context2`
  - metadata associees
- chaque sample devient une requete `question` avec deux passages gold: `context1` et `context2`

## 7.3 Parametres experimentaux importants

### `index_name`

Nom logique de l'index a utiliser pour la run.

### `top_k`

Nombre final de resultats retournes par strategie.

### `max_query_chars`

Parametre critique pour la stabilite des experiences.

Il sert a:
- exclure les queries aberrantes ou gigantesques,
- eviter les deconnexions NextPlaid sur des tailles extremes,
- rendre `semantic` et `hybrid` evaluables de facon plus serieuse.

### `streaming`

Permet de charger le dataset Hugging Face en streaming.

Sur machine modeste, c'est souvent le meilleur choix:
- pas de telechargement complet,
- pas de charge RAM enorme,
- iteration progressive.

## 7.4 Exemple de payloads recommandes

### FIND

```json
{
  "dataset_name": "kensho/FIND",
  "split": "validation",
  "max_samples": 20,
  "index_name": "default",
  "top_k": 10,
  "strategies": ["baseline", "lexical", "semantic", "hybrid", "rg"],
  "streaming": true,
  "max_query_chars": 8192
}
```

### Wikipedia Contradict

```json
{
  "dataset_name": "ibm-research/Wikipedia_contradict_benchmark",
  "split": "train",
  "max_samples": 20,
  "index_name": "default",
  "top_k": 10,
  "strategies": ["baseline", "lexical", "semantic", "hybrid", "rg"],
  "streaming": true,
  "max_query_chars": 8192
}
```

## 7.5 Historique des experiences

Les runs sont persistees en SQLite dans:

- [experiments.db](/home/jean/projects/doctorat/projet-1/backend-regex/storage/experiments.db)

Contenu persiste:

- configuration de run,
- dataset,
- split,
- meilleure strategie par rappel,
- rapports agreges,
- details par sample.

Objectif:
- garder un historique reel,
- comparer dans le temps,
- pouvoir rouvrir une run et la relire.

## 7.6 Page detail d'experience

La page detail permet maintenant:

1. choisir une strategie,
2. choisir un sample,
3. lire la question/probleme exact,
4. voir le gold attendu,
5. voir les passages recuperes,
6. voir rang, score, recall, MRR, nDCG, latence,
7. ouvrir un lecteur dedie de sample avec rendu Markdown.

Cette page sert a repondre a la question:

"quel probleme a ete pose au moteur, et qu'a-t-il effectivement retourne ?"

## 7.7 Interpretation correcte des metriques

### Recall@K

Mesure si les bonnes preuves apparaissent dans les `K` premiers resultats.

### MRR

Mesure a quelle hauteur apparait le premier bon resultat.

### nDCG@K

Mesure la qualite de l'ordre des resultats en tenant compte des pertinences.

Important:
- le `nDCG` standard est borne entre `0` et `1`.
- si tu vois une valeur > 1, il faut suspecter un bug de reporting ou un vieux run.

### Candidate count

Nombre de candidats vus avant la coupe finale.

### Candidate kept count

Nombre final de resultats gardes et exposes.

## 7.8 Ce qu'il faut retenir des strategies

Dans l'etat actuel:

- `lexical` est souvent une tres bonne strategie economique de candidate generation,
- `rg` est utile comme reference robuste regex,
- `semantic` apporte potentiellement du sens mais peut etre plus fragile sur certains benchmarks,
- `hybrid` n'est pas automatiquement meilleur si la fusion ou le benchmark ne lui donnent pas d'avantage.

Il faut donc juger chaque run:

- par dataset,
- par type de question,
- par latence,
- par gain reel de recall/ranking.

## 8. Dashboard et visualisation

Le Dashboard n'est plus une page statique.

Il affiche maintenant:

- etat global du systeme,
- nombre de documents,
- historique recent des runs,
- resume des experiences,
- meilleures tendances de recall/latence.

Il sert a avoir une vue d'ensemble rapide avant d'ouvrir le detail d'une run.

## 9. Scenarios d'usage recommandes

## 9.1 Tester un document reel

1. uploader un document,
2. attendre `completed`,
3. verifier le contenu extrait,
4. lancer `LLM Analyze` sur des claims reelles,
5. comparer `hybrid`, `lexical`, `semantic`, `rg` si necessaire.

## 9.2 Tester la qualite retrieval

1. ouvrir `Experiences`,
2. choisir le dataset,
3. lancer la run,
4. ouvrir la run detaillee,
5. comparer sample par sample.

## 9.3 Diagnostiquer une strategie

1. ouvrir une run,
2. selectionner la strategie,
3. choisir un sample raté,
4. lire le gold,
5. lire les passages recuperes,
6. verifier si le probleme est:
   - rappel,
   - ranking,
   - bruit,
   - query trop longue,
   - moteur semantique en erreur.

## 9.4 Machine peu puissante

Sur machine modeste:

1. privilegier `streaming=true` pour les datasets Hugging Face,
2. limiter `max_samples`,
3. conserver `max_query_chars`,
4. utiliser `lexical` ou `rg` pour des tests rapides,
5. reserver `semantic`/`hybrid` aux runs plus couteuses mais plus informatives.

## 9.5 Gros PDF et OCR

Le pipeline peut traiter un PDF long, par exemple 50 pages, mais il faut distinguer:

1. nombre de pages,
2. taille reelle du fichier,
3. cout reseau pour l'envoi au provider OCR.

Etat actuel:

- le PDF est accepte jusqu'a 50 MB
- l'OCR decoupe ensuite le traitement en chunks de 15 pages
- mais le document initial reste envoye au provider OCR

Risque connu:

- pour un PDF lourd, l'echec peut arriver avant l'analyse OCR, pendant l'upload du payload vers le provider
- dans ce cas, le worker remonte maintenant un statut explicite de type `ocr_upload_timeout`

Consequence pratique:

- un document de 50 pages est supporte en principe
- mais un PDF tres lourd peut encore echouer a l'etape d'envoi OCR

Symptomes a surveiller:

- `status = failed`
- `details.stage = ocr_upload_timeout`
- message du type `OCR upload timed out while sending the document to the provider`

## 10. Limites connues

1. `/detect` n'est pas encore retrieval-driven.
2. `hybrid` n'est pas encore la cascade finale cible.
3. le benchmark FIND reste soumis a l'acces Hugging Face gated.
4. les anciennes runs SQLite peuvent ne pas contenir les nouveaux champs detailles.
5. `semantic` depend fortement de la stabilite NextPlaid et de la taille des queries.
6. `lexical` / `rg` restent lies a un index local en memoire de processus.
7. l'OCR de gros PDFs peut encore etre limite par le cout d'upload vers le provider.

## 11. Positionnement par rapport a l'architecture cible

Le document [architetcure.md](/home/jean/projects/doctorat/projet-1/docs-regex/architetcure.md) decrit une cible plus ambitieuse:

- prefiltrage lexical,
- retrieval semantique fin,
- comparaison structuree,
- compression minimale,
- LLM si utile.

Etat actuel:

- la recherche produit est deja bien avancee,
- l'experimentation est serieuse et persistante,
- la lecture des samples est maintenant exploitable,
- la detection doit encore etre alignee sur ce design retrieval-driven.

## 12. Resume executif

Aujourd'hui, le meilleur usage de l'application est:

1. document reel -> extraction -> indexation,
2. retrieval via `hybrid` ou `lexical`,
3. analyse LLM sur document pour les claims importantes,
4. experimentation sur FIND et Wikipedia Contradict pour comparer les strategies,
5. lecture detaillee des runs pour comprendre precisement les echecs et les succes.

Ce document doit etre lu comme la reference d'usage actuelle, pas comme une promesse d'architecture future.
