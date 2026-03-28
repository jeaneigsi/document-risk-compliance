Oui. Je te refais toute la revue complète, proprement, avec la logique de bout en bout.

Le document Word reste ici si tu veux garder une version formelle : [document_cadrage_architecture_incoherences.docx](sandbox:/mnt/data/document_cadrage_architecture_incoherences.docx)

## 1. Le problème que tu veux résoudre

Le problème de fond, ce n’est pas juste “chercher dans des documents”. Le vrai problème, c’est que les entreprises ont des documents longs, versionnés, parfois bruités ou OCRisés, et qu’elles doivent repérer des incohérences coûteuses : dates divergentes, montants incompatibles, clauses contradictoires, métadonnées incohérentes, violations de règles documentaires. Le deuxième problème, tout aussi important, c’est que les pipelines LLM coûtent cher et deviennent lents quand on envoie trop de contexte. Ton sujet combine donc deux enjeux : **détecter l’incohérence** et **réduire le contexte nécessaire pour la prouver**. ([Hugging Face][1])

La formulation propre de la problématique est celle-ci :
**comment détecter automatiquement des incohérences inter-documents et inter-versions, tout en minimisant le contexte envoyé au modèle afin de réduire coût et latence sans perdre en fiabilité ?**

## 2. Pourquoi ce sujet a de la valeur économique

Pour une entreprise, l’impact se voit sur trois axes.

D’abord, il y a la réduction du risque. Une incohérence non détectée dans un contrat, un rapport ou un livrable peut conduire à un rejet, un retard, une non-conformité ou un litige. Des jeux comme CUAD montrent bien à quel point la structure des clauses et leur extraction ont une valeur opérationnelle forte dans des documents complexes. ([Hugging Face][2])

Ensuite, il y a la réduction du temps humain. Aujourd’hui, beaucoup de vérifications se font encore à la main, en relisant plusieurs versions ou plusieurs documents proches. Si ton système remonte directement les passages conflictuels avec justification, il transforme une tâche de lecture diffuse en une tâche de validation ciblée.

Enfin, il y a la réduction du coût IA. LongBench a été conçu précisément dans le contexte des longs contextes et rappelle que les coûts d’évaluation et d’inférence augmentent fortement avec la taille des entrées ; il couvre des tâches longues avec des longueurs moyennes souvent entre 5k et 15k, ce qui reflète bien la pression économique du contexte long. ([Hugging Face][3])

## 3. L’idée centrale de la solution

Ta solution n’est pas un “chatbot documentaire”. C’est un **système de décision documentaire orienté risque**.

L’idée est simple en apparence : au lieu d’envoyer un gros bloc de documents à un LLM, tu construis une chaîne de traitement qui prépare les bonnes preuves, les compare intelligemment, élimine le bruit, puis n’envoie au modèle que le **contexte minimal suffisant** pour trancher et expliquer.

Autrement dit, ton innovation est à l’intersection de trois choses :
la **recherche de preuves**, la **détection d’incohérences**, et la **compression intelligente du contexte**.

## 4. Le rôle exact de Cursor et de NextPlaid

C’est important de bien les distinguer.

Le blog de Cursor ne t’apporte pas un moteur complet de raisonnement. Il t’apporte une idée d’architecture pour la **recherche lexicale ultra rapide**.

**Problème identifié par Cursor** : `ripgrep` est très rapide par fichier, mais devient un goulot d’étranglement dans les très gros dépôts car il doit scanner **tous** les fichiers. Cursor observe des appels `rg` dépassant **15 secondes** dans de grands monorepos enterprise. ([Cursor][4])

**Solution technique** : Index local avec **trigrammes + index inversé**
- Divise le texte en n-grams (trigrammes)
- Index inversé pour réduire l’espace candidat **avant** d’exécuter la regex
- Inspiré de l’algorithme de 1993 (Zobel, Moffat, Sacks-Davis : *"Searching Large Lexicons for Partially Specified Terms using Compressed Inverted Files"*)
- Approche similaire aux indexes syntactiques (ctags, LSP) mais appliquée aux regex

**Gain mesuré** : Réduction drastique du nombre de fichiers à scanner, donc de la latence totale.

NextPlaid, lui, joue un autre rôle. Le dépôt GitHub le présente comme un moteur de recherche **multi-vector**, avec ColGREP construit au-dessus.

**Architecture NextPlaid** ([GitHub][5]) :
- **ColGREP** = combinaison explicite de **regex filtering** + **semantic ranking**
- **Licence** : Apache-2.0 (open source, utilisable en recherche)
- **Multi-vector** : environ 300 embeddings de dimension 128 par document
- **Scoring** : MaxSim pour agréger les scores multi-vector
- **Optimisations** :
  - Quantization 2-bit ou 4-bit pour réduire la taille mémoire
  - Index memory-mapped pour accès rapide
  - Préfiltrage par métadonnées via SQLite
- **Positionnement** : Retrieval sémantique fin, idéalement après un premier filtrage lexical

La lecture correcte est donc celle-ci :

Cursor-like = **pruning lexical très rapide**
NextPlaid = **retrieval sémantique fin**
Ton système = **comparaison, détection, compression, explication**

**Synthèse de la complémentarité** :

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUX DE RECHERCHE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Corpus documentaire                                            │
│        ↓                                                         │
│  ┌──────────────────┐                                          │
│  │  Cursor-like     │  Index trigrammes + inversé              │
│  │  (pruning)       │  Réduit espace candidat de 100% → ~5%     │
│  └────────┬─────────┘                                          │
│           ↓                                                      │
│  ┌──────────────────┐                                          │
│  │  NextPlaid       │  Multi-vector + ColGREP                  │
│  │  (semantic)      │  Rangement par pertinence sémantique     │
│  └────────┬─────────┘                                          │
│           ↓                                                      │
│  Evidence candidates (top-k)                                    │
│           ↓                                                      │
│  ┌──────────────────┐                                          │
│  │  Ton détecteur   │  Comparaison + Compression               │
│  └──────────────────┘                                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Pourquoi cette hybrideration fonctionne** :

1. **Cursor-like** élimine le bruit lexical très vite (cas exacts, patterns forts)
2. **NextPlaid** récupère les reformulations et contradictions sémantiques
3. **Ton système** ne traite que le contexte minimal prouvé

C'est exactement l'architecture pour laquelle **FIND** fournit le gold standard d'évaluation.

## 5. L’architecture concrète

Je te la raconte comme un flux.

### 5.1 Ingestion documentaire

Tu reçois des fichiers bruts : PDF, scans, versions successives, contrats, rapports, procédures. À ce stade, il faut distinguer trois objets : le document logique, sa version, et le fichier physique. C’est la base pour comparer proprement V1, V2, V3 au lieu de mélanger tout.

### 5.2 Parsing structuré

Tu transformes chaque document en une représentation canonique : pages, blocs, sections, tableaux, entités, métadonnées, qualité OCR. Le point clé est de ne pas aplatir le document en simple texte brut. Il faut pouvoir dire plus tard : “page 4, section budget, tableau B, ligne 12”.

### 5.3 Normalisation métier

À partir des blocs extraits, tu dérives des champs structurés : date de livraison, budget total, référence projet, numéro de révision, statut d’approbation. Cette couche est capitale parce qu’elle rend les incohérences numériques et calendaires beaucoup plus faciles à comparer.

### 5.4 Construction des evidence units

Tu découpes la matière en unités de preuve réutilisables : paragraphes, lignes de tableau, clauses, champs métier sérialisés. Ce sont ces unités que tu vas indexer et comparer.

### 5.5 Double recherche : Cursor-like puis NextPlaid

D’abord, tu appliques un préfiltrage lexical inspiré de Cursor. Il sert à éliminer vite tout ce qui n’a presque aucune chance de contenir le bon motif ou le bon champ. Ensuite, sur ce sous-ensemble, tu lances le retrieval sémantique multi-vector de NextPlaid pour mieux remonter les passages proches en sens, y compris quand les formulations changent. Cursor améliore donc la rapidité et le pruning ; NextPlaid améliore la qualité sémantique des preuves candidates. ([Cursor][4])

### 5.6 Génération des candidats de comparaison

Le système forme des paires ou groupes à comparer : même champ entre deux versions, même clause entre deux documents, même référence avec valeurs divergentes, même section avec formulations incompatibles.

### 5.7 Détection d’incohérences

Là, tu fais une cascade.

D’abord des détecteurs déterministes pour les cas simples : dates différentes, montants incompatibles, code documentaire non conforme. Ensuite des comparateurs spécialisés pour les cas plus subtils : clauses, tableaux, sections proches. Enfin, seulement si nécessaire, un LLM ciblé qui tranche un micro-problème très bien préparé.

### 5.8 Compression intelligente du contexte

C’est ton cœur scientifique. Tu construis un **minimal context bundle** : seulement les extraits indispensables, plus éventuellement une règle métier ou une métadonnée structurante. Le but est de prouver sans surcharger.

### 5.9 Décision et explication

La sortie n’est pas juste “conflict detected”. Elle doit contenir le type d’écart, la gravité, les documents concernés, les extraits de preuve, une explication lisible, et une recommandation d’action.

## 6. Pourquoi cette architecture est forte

Elle est forte parce qu’elle est hiérarchique.

Tu n’utilises pas un LLM pour faire ce qu’un index peut faire plus vite. Tu n’utilises pas un moteur sémantique pour faire ce qu’un match exact peut faire mieux. Tu n’envoies pas 40 pages quand 3 extraits suffisent.

En clair, tu passes de la logique naïve :
“gros contexte + LLM”

à une logique beaucoup plus mature :
“pruning exact → retrieval sémantique → comparaison ciblée → compression → LLM si utile”

C’est exactement le genre d’architecture qui a une crédibilité doctorale, parce qu’elle te permet de formuler des hypothèses testables sur la qualité, la latence et le coût.

## 7. Les objectifs du projet

Il faut les poser à trois niveaux.

Le premier objectif est fonctionnel : détecter des incohérences entre documents et versions avec preuves explicites.

Le deuxième objectif est économique : réduire significativement le nombre de tokens, la latence et le coût par analyse.

Le troisième objectif est scientifique : comparer plusieurs stratégies de recherche et de construction du contexte pour comprendre lesquelles donnent le meilleur compromis qualité/coût.

## 8. Les hypothèses de recherche

Tu peux poser au moins quatre hypothèses solides.

La première : un préfiltrage lexical inspiré de Cursor réduit fortement l’espace candidat et améliore la latence sur les cas à forte signature textuelle. Cursor présente précisément cette idée comme une réponse au coût des recherches regex sur de très grands dépôts. ([Cursor][4])

La deuxième : un retrieval multi-vector comme NextPlaid améliore le rappel sur les reformulations et contradictions non littérales par rapport à un moteur lexical seul. Le dépôt insiste justement sur l’intérêt du multi-vector et du MaxSim pour aller au-delà d’un embedding unique. ([GitHub][5])

La troisième : une stratégie hybride Cursor-like + NextPlaid donne un meilleur compromis que chacune des deux prises isolément.

La quatrième : un contexte minimal bien construit conserve l’essentiel de la qualité de détection tout en réduisant nettement coût et latence.

## 9. Le framework d’évaluation

C’est ici que ton projet devient sérieux. Tu ne mesures pas juste “ça marche / ça ne marche pas”.

Il te faut quatre familles de métriques.

### 9.1 Qualité de la recherche

Tu mesures si le moteur remonte les bonnes preuves.

Les métriques naturelles sont Recall@k, MRR, nDCG, rang des gold evidences, taille de l’ensemble candidat, et taux de pruning. C’est là que tu vas comparer baseline lexicale, Cursor-like, NextPlaid seul, puis hybride.

### 9.2 Qualité de détection

Tu mesures précision, rappel et F1 sur la détection des incohérences. Il faut stratifier au moins par type : conflit lexical exact, conflit de champ structuré, contradiction reformulée, conflit mixte texte/tableau/OCR.

### 9.3 Qualité d’explication

Le système a-t-il donné les bons extraits ? Le type de conflit est-il bien qualifié ? L’explication est-elle exploitable ? Le plus simple est d’annoter un gold explanation minimal et des evidence spans.

### 9.4 Performance économique

Tu mesures nombre de tokens envoyés, taux de compression, coût estimé, latence de recherche, latence de pipeline et nombre d’appels LLM.

L’objectif n’est pas d’être meilleur partout. L’objectif est de montrer un compromis clair, par exemple : qualité équivalente avec moins de tokens, ou meilleur rappel pour un coût similaire.

## 10. Le framework de monitoring

Il faut séparer monitoring runtime et suivi expérimental.

Le monitoring runtime sert à comprendre le comportement du système en exécution : latence, erreurs, taille du contexte, nombre de candidats, modules lents, nombre d’appels LLM.

Le suivi expérimental sert à comparer proprement les variantes du pipeline : stratégie de recherche, version de l’index, version du prompt, politique de compression, modèle utilisé.

La bonne approche reste celle qu’on avait cadrée : **OpenTelemetry** pour les traces et métriques transverses du pipeline, et **Langfuse** pour les traces LLM, les datasets, les runs, les scores et les expériences. Cette combinaison te donne à la fois une vision “produit” et une vision “recherche”. ([GitHub][5])

À tracer absolument pour chaque run :
`analysis_id`, `pipeline_version`, `search_strategy`, `candidate_count`, `candidate_kept_count`, `compression_ratio`, `token_input`, `latency_ms`, `llm_calls_count`, `final_status`.

## 11. La dimension comparative autour de Cursor

C’est un point important que tu as ajouté, et il renforce clairement le sujet.

Tu ne veux plus seulement évaluer un pipeline de détection. Tu veux aussi comparer des **philosophies de recherche**.

Les variantes minimales à tester sont :

la baseline lexicale simple,
une implémentation Cursor-like de pruning trigramme/index inversé,
NextPlaid seul,
et l’hybride Cursor-like + NextPlaid.

Cette couche comparative devient un objet de recherche à part entière :
**quelle stratégie de recherche fournit les meilleures preuves pour la détection d’incohérences, au meilleur compromis entre rappel, précision, latence et coût ?**

Ça, c’est une vraie question de thèse appliquée.

## 12. Les datasets à utiliser

Le plus intelligent est de ne pas dépendre d’un seul dataset. Il te faut un socle hybride.

### 12.1 FIND

FIND est très aligné avec ton sujet. La carte du dataset dit qu’il contient des documents avec incohérences annotées et insérées, avec un `problem_text`, une `description` humaine, et des `evidence_dicts` structurés pointant vers les zones de l’incohérence. Le dataset prévient aussi très clairement que les documents ont été **intentionnellement altérés** pour la recherche et qu’ils ne doivent pas être utilisés comme documents authentiques. ([Hugging Face][1])

Lien : [https://huggingface.co/datasets/kensho/FIND](https://huggingface.co/datasets/kensho/FIND)

**Contraintes d’utilisation** :
- **Usage exclusif** : *Noncommercial Research Uses* uniquement (recherche académique autorisée)
- **Restrictions** :
  - Pas d’utilisation commerciale directe ou indirecte
  - Pas de redistribution sans consentement écrit de Kensho
  - Les modèles entraînés sur FIND ne peuvent pas être utilisés pour un usage commercial

**Structure du dataset** :
- `problem_text` — description du problème/incohérence
- `description` — explication humaine détaillée
- `evidence_dicts` — zones preuves structurées pointant vers l’incohérence (spans, pages)
- ⚠️ **Documents altérés** — ne pas utiliser comme sources authentiques ou pour la prise de décision

Pourquoi l’utiliser :
parce qu’il est excellent pour tester **détection + evidence retrieval + explication**.

### 12.2 Wikipedia Contradict Benchmark

Ce dataset IBM contient **253 instances annotées humainement** de conflits de connaissance du monde réel, avec licence MIT selon la carte Hugging Face. ([Hugging Face][6])

Lien : [https://huggingface.co/datasets/ibm-research/Wikipedia_contradict_benchmark](https://huggingface.co/datasets/ibm-research/Wikipedia_contradict_benchmark)

Pourquoi l’utiliser :
pour tester les contradictions sémantiques réelles, surtout quand l’incompatibilité n’est pas une simple différence de valeur.

### 12.3 LongBench

LongBench est présenté comme un benchmark bilingue et multitâche d’évaluation du long contexte, composé de **six grandes catégories et vingt tâches**, avec des longueurs moyennes souvent entre **5k et 15k**. ([Hugging Face][3])

Lien : [https://huggingface.co/datasets/yanbingzheng/LongBench](https://huggingface.co/datasets/yanbingzheng/LongBench)

Pourquoi l’utiliser :
pour évaluer la **compression de contexte** et le comportement sur des contextes longs.

### 12.4 MP-DocVQA

La carte précise qu’il s’agit d’un dataset de question answering sur documents scannés multipages, avec **jusqu’à 20 pages par document**. ([Hugging Face][7])

Lien : [https://huggingface.co/datasets/rubentito/mp-docvqa](https://huggingface.co/datasets/rubentito/mp-docvqa)

Pourquoi l’utiliser :
pour tester ton pipeline sur du **document visuel multi-pages** avec bruit de scan.

### 12.5 CUAD

CUAD est décrit comme un corpus de **plus de 13 000 labels** sur **510 contrats commerciaux**, annotés manuellement, couvrant **41 catégories** de clauses importantes. ([Hugging Face][2])

Lien : [https://huggingface.co/datasets/theatticusproject/cuad](https://huggingface.co/datasets/theatticusproject/cuad)

Pourquoi l’utiliser :
pour bâtir des expériences orientées **compliance** et documents juridiques structurés.

### 12.6 ContractNLI

Même si la carte Hugging Face affichée dans cette session est moins explicite sur les champs descriptifs, ContractNLI reste utile comme source de cas de raisonnement contractuel et d’inférence documentaire quand tu veux pousser la comparaison de clauses et la cohérence juridique. ([Hugging Face][8])

Lien : [https://huggingface.co/datasets/kiddothe2b/contract-nli](https://huggingface.co/datasets/kiddothe2b/contract-nli)

---

## 13. Plan d’action datasets

### 13.1 Stratégie prioritaire

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE 1: Démarrage (100-200 docs FIND)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        FIND (principal)                              │   │
│  │  • Télécharger validation split                                     │   │
│  │  • Créer loader: FIND → Evidence Units                              │   │
│  │  • Implémenter métriques: Recall@k sur evidence_dicts                │   │
│  │  • Baseline: détection sans pipeline                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   Wikipedia Contradict (parallèle)                   │   │
│  │  • Tester capacité sémantique NextPlaid                             │   │
│  │  • Comparer vs baseline lexicale                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       LongBench (parallèle)                          │   │
│  │  • Valider compression de contexte                                  │   │
│  │  • Mesurer: compression_ratio vs qualité                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE 2: MP-DocVQA (robustesse)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Tests OCR bruité                                                         │
│  • Incohérences inter-pages                                                 │
│  • Tableaux scannés                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 13.2 Commandes d’accès aux datasets

```python
# Installation dépendance FIND
pip install pyarrow==17.0.0

# Chargement des datasets
from datasets import load_dataset

# FIND - Dataset principal
find = load_dataset("kensho/FIND", split="validation")
# Structure: problem_text, description, evidence_dicts

# Wikipedia Contradict - Contradictions sémantiques
wiki = load_dataset("ibm-research/Wikipedia_contradict_benchmark")
# 253 instances, licence MIT

# LongBench - Compression contexte long
longbench = load_dataset("yanbingzheng/LongBench")
# Contextes 5k-15k tokens, 20 tâches

# MP-DocVQA - Robustesse OCR (Phase 2)
mpdocvqa = load_dataset("rubentito/mp-docvqa")
# Jusqu’à 20 pages par document, scans bruités

# CUAD - Contrats et compliance (optionnel)
cuad = load_dataset("theatticusproject/cuad")
# 510 contrats, 13 000 labels, 41 catégories
```

### 13.3 Structure technique FIND

```python
# Exemple de structure FIND
{
    "problem_text": "Le document complet avec incohérence insérée...",
    "description": "La date de livraison (15 mars) contredit le délai de 30 jours...",
    "evidence_dicts": [
        {
            "type": "date_contradiction",
            "spans": [
                {"text": "15 mars 2024", "page": 2, "start": 145, "end": 156},
                {"text": "délai de 30 jours", "page": 1, "start": 89, "end": 105}
            ]
        }
    ]
}
```

### 13.4 Protocole expérimental par dataset

| Dataset | Objectif principal | Métriques clés |
|---------|-------------------|----------------|
| **FIND** | Détection + evidence retrieval | Recall@k, Evidence span accuracy, F1 détection |
| **Wikipedia Contradict** | Contradictions sémantiques | Précision sémantique vs baseline lexicale |
| **LongBench** | Compression contexte | compression_ratio, qualité maintenue, coût/token |
| **MP-DocVQA** | Robustesse OCR/multi-pages | Recall sur documents bruités, inter-page detection |
| **CUAD** | Compliance juridique | Clause extraction accuracy, coherence checking |

## 14. Le bon choix de dataset global

Le bon move n’est pas “je prends un dataset et c’est fini”.

Le meilleur design est :

FIND comme base principale pour la détection d’incohérences,
Wikipedia Contradict pour les contradictions sémantiques,
LongBench pour la compression et le long contexte,
MP-DocVQA pour les scans multi-pages,
et un mini-corpus métier maison pour coller à ton usage industriel.

C’est ce mélange qui te donnera une crédibilité à la fois académique et entreprise.

## 15. Le protocole expérimental conseillé

Le protocole minimal doit comparer au moins quatre pipelines :

baseline lexicale simple,
Cursor-like seul,
NextPlaid seul,
Cursor-like + NextPlaid.

Et pour chaque pipeline, tu mesures deux niveaux.

Niveau recherche : Recall@k, MRR, rang des preuves, taille des candidats, latence.

Niveau tâche finale : précision, rappel, F1 de détection, qualité d’explication, nombre de tokens, coût, latence totale.

Là, tu pourras produire des résultats vraiment parlants. Typiquement :
la recherche Cursor-like accélère très bien les cas exacts, NextPlaid récupère mieux les reformulations, et l’hybride donne le meilleur compromis global.

## 16. Le message final à retenir

Ton projet, au fond, n’est pas un RAG de plus. C’est une **architecture de vérification documentaire**.

Sa force vient du fait qu’elle traite séparément :
la recherche exacte,
la recherche sémantique,
la comparaison métier,
la compression du contexte,
et l’explication finale.

C’est exactement ce qui lui donne une valeur doctorale. Tu ne te contentes pas d’utiliser un modèle ; tu conçois une chaîne d’inférence documentaire mesurable, optimisable et économiquement défendable.

Le cœur du sujet, une fois tout remis à plat, tient dans cette phrase :

**concevoir un pipeline capable de retrouver les bonnes preuves, détecter les incohérences entre documents longs, et transmettre au modèle seulement le contexte minimal nécessaire, afin d’optimiser simultanément fiabilité, coût et latence.**

La suite la plus utile maintenant, c’est que je te transforme cette revue en **plan de mémoire / plan de papier scientifique**, avec les chapitres déjà ordonnés.

[1]: https://huggingface.co/datasets/kensho/FIND "kensho/FIND · Datasets at Hugging Face"
[2]: https://huggingface.co/datasets/theatticusproject/cuad "theatticusproject/cuad · Datasets at Hugging Face"
[3]: https://huggingface.co/datasets/yanbingzheng/LongBench "yanbingzheng/LongBench · Datasets at Hugging Face"
[4]: https://cursor.com/blog/fast-regex-search "Fast regex search: indexing text for agent tools · Cursor"
[5]: https://github.com/lightonai/next-plaid/ "GitHub - lightonai/next-plaid: NextPlaid, ColGREP: Multi-vector search, from database to coding agents. · GitHub"
[6]: https://huggingface.co/datasets/ibm-research/Wikipedia_contradict_benchmark "ibm-research/Wikipedia_contradict_benchmark · Datasets at Hugging Face"
[7]: https://huggingface.co/datasets/rubentito/mp-docvqa "rubentito/mp-docvqa · Datasets at Hugging Face"
[8]: https://huggingface.co/datasets/kiddothe2b/contract-nli "kiddothe2b/contract-nli · Datasets at Hugging Face"

Oui, tu as raison. Il faut une vraie section finale dédiée.

Tu peux ajouter exactement ceci à la fin du document.

## 17. Références et liens à consulter

### Articles et briques techniques

1. **Cursor — Fast regex search: indexing text for agent tools**
   Article central pour comprendre l’idée de préfiltrage lexical local, l’indexation pour regex, et pourquoi cette approche est utile avant un retrieval plus coûteux. Cursor explique notamment l’objectif de réduire les recherches `ripgrep` longues dans de très grands dépôts. ([Cursor][1])
   Lien : `https://cursor.com/blog/fast-regex-search`

2. **LightOn — NextPlaid (GitHub)**
   Repo open source de la brique multi-vector à intégrer dans la couche de retrieval sémantique. C’est la référence à consulter pour l’API, l’architecture, la licence et le fonctionnement général. La licence affichée est Apache-2.0. ([GitHub][2])
   Lien : `https://github.com/lightonai/next-plaid`

3. **LightOn — présentation NextPlaid / écosystème ColGREP**
   Utile pour comprendre le positionnement de NextPlaid, FastPlaid et ColGREP dans le même écosystème. ([lighton.ai][3])
   Lien : `https://lighton.ai/lighton-blogs/introducing-lighton-nextplaid`

### Datasets à utiliser

4. **FIND — kensho/FIND**
   Dataset très aligné avec ton sujet, centré sur la détection d’incohérences dans des documents, avec éléments de preuve annotés. ([Hugging Face][4])
   Lien : `https://huggingface.co/datasets/kensho/FIND`

5. **Wikipedia Contradict Benchmark — ibm-research**
   Dataset utile pour tester les contradictions sémantiques réelles entre passages, avec 253 instances annotées humainement. ([Hugging Face][5])
   Lien : `https://huggingface.co/datasets/ibm-research/Wikipedia_contradict_benchmark`

6. **LongBench**
   Benchmark utile pour évaluer la robustesse sur contexte long et la compression de contexte. ([Hugging Face][4])
   Lien : `https://huggingface.co/datasets/yanbingzheng/LongBench`

7. **MP-DocVQA**
   Utile pour les documents multi-pages scannés et les cas visuels/OCR.
   Lien : `https://huggingface.co/datasets/rubentito/mp-docvqa`

8. **CUAD**
   Dataset pertinent pour les expériences orientées contrats, conformité et analyse de clauses.
   Lien : `https://huggingface.co/datasets/theatticusproject/cuad`

9. **ContractNLI**
   Dataset complémentaire pour le raisonnement sur contrats et cohérence documentaire.
   Lien : `https://huggingface.co/datasets/kiddothe2b/contract-nli`

### Références à lire en priorité

Pour aller vite sans te disperser, je te conseille de lire dans cet ordre :

* Cursor fast regex search
* NextPlaid GitHub
* FIND
* Wikipedia Contradict Benchmark
* LongBench

Comme ça, tu couvres d’abord :
le **pruning lexical**,
le **retrieval sémantique**,
la **détection d’incohérences**,
puis la **compression sur long contexte**.
