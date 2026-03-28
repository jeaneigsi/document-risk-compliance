# Référence des Métriques

Ce document décrit exhaustivement toutes les métriques utilisées dans le système de détection d'incohérences documentaires, leurs formules mathématiques, leur interprétation et leurs seuils.

---

## Table des Matières

1. [Métriques de Recherche (IR)](#1-métriques-de-recherche-ir)
2. [Métriques de Détection](#2-métriques-de-détection)
3. [Métriques Économiques](#3-métriques-économiques)
4. [Métriques de Sévérité](#4-métriques-de-sévérité)
5. [Tableau Récapitulatif](#5-tableau-récapitulatif)

---

## 1. Métriques de Recherche (IR)

Les métriques d'Information Retrieval mesurent la qualité de la recherche de preuves/documentaires.

### 1.1 Recall@K (Rappel à K)

**Définition** : Proportion des documents pertinents effectivement retrouveacute;s dans les K premiers résultats.

**Formule** :

$$\text{Recall@K} = \frac{|\{documents\;pertinents\} \cap \{K\;premiers\;résultats\}|}{|\{documents\;pertinents\}|}$$

**Implémentation** :

```python
def recall_at_k(relevant_ids: set[str], retrieved_ids: list[str], k: int) -> float:
    top = retrieved_ids[:k]
    hits = len(relevant_ids & set(top))
    return hits / len(relevant_ids) if relevant_ids else 0.0
```

**Interprétation** :

| Recall@K | Niveau | Signification |
|----------|--------|---------------|
| 0.80 - 1.00 | Excellent | La plupart des preuves retrouvées |
| 0.60 - 0.79 | Bon | Une bonne partie des preuves |
| 0.40 - 0.59 | Moyen | Partie significative manquée |
| 0.00 - 0.39 | Faible | Trop de preuves manquées |

**Exemple concret** :

```
Relevants: [doc_A, doc_B, doc_C, doc_D, doc_E]
Retrieved (K=3): [doc_A, doc_C, doc_F]

Hits: doc_A, doc_C = 2
Recall@3 = 2 / 5 = 0.40 (40%)

Interpretation: 40% des documents pertinents ont été retrieves dans le top 3.
```

---

### 1.2 MRR (Mean Reciprocal Rank)

**Définition** : Rang moyen réciproque. Mesure la qualité du classement en pénalisant les cas où le premier résultat pertinent apparaît tard.

**Formule** :

$$\text{MRR} = \frac{1}{N} \sum_{i=1}^{N} \frac{1}{rang_i}$$

où $rang_i$ = rang du premier résultat pertinent pour la requête $i$.

**Implémentation** :

```python
def mrr(relevant_ids: set[str], retrieved_ids: list[str]) -> float:
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0
```

**Interprétation** :

| MRR | Niveau | Signification |
|-----|--------|---------------|
| 0.90 - 1.00 | Excellent | Le résultat pertinent est en 1ère position |
| 0.70 - 0.89 | Bon | Résultat pertinent dans le top 2-3 |
| 0.50 - 0.69 | Moyen | Résultat pertinent plus loin |
| 0.00 - 0.49 | Faible | Pas de résultat pertinent |

**Exemple concret** :

```
Requete 1: Retrieved [A, B, C], relevant = {A} → rang=1 → 1/1 = 1.0
Requete 2: Retrieved [X, Y, Z], relevant = {Z} → rang=3 → 1/3 = 0.333
Requete 3: Retrieved [P, Q, R], relevant = {R} → rang=3 → 1/3 = 0.333

MRR = (1.0 + 0.333 + 0.333) / 3 = 0.555
```

**Usage** : Important pour les systèmes où l'utilisateur veut une réponse rapide. Un MRR de 0.9 signifie que 90% du temps, la réponse est dans le top 1.

---

### 1.3 nDCG@K (Normalized Discounted Cumulative Gain)

**Définition** : Mesure sophisticated qui prend en compte à la fois :
1. L'ordre des résultats (plus c'est haut, mieux c'est)
2. Le degré de pertinence (pas juste binaire : partiellement pertinent compte)

**Formule** :

$$\text{DCG@K} = \sum_{i=1}^{K} \frac{rel_i}{\log_2(i+1)}$$

$$\text{IDCG@K} = \text{DCG@K ideal} = \sum_{i=1}^{K} \frac{rel^{ideal}_i}{\log_2(i+1)}$$

$$\text{nDCG@K} = \frac{\text{DCG@K}}{\text{IDCG@K}}$$

où $rel_i$ = pertinence du résultat à la position $i$ (0 à 1).

**Implémentation** :

```python
def ndcg_at_k(relevance_by_id: dict[str, float], retrieved_ids: list[str], k: int) -> float:
    top = retrieved_ids[:k]
    
    # DCG
    dcg = 0.0
    for i, doc_id in enumerate(top, start=1):
        rel = float(relevance_by_id.get(doc_id, 0.0))
        if rel > 0:
            dcg += rel / math.log2(i + 1)
    
    # IDCG (ideal)
    ideal_rels = sorted((float(v) for v in relevance_by_id.values() if v > 0), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(ideal_rels, start=1):
        idcg += rel / math.log2(i + 1)
    
    return dcg / idcg if idcg > 0 else 0.0
```

**Différence avec Recall/MRR** :

| Métrique | Prend en compte l'ordre | Prend en compte la pertinence graduelle |
|----------|-------------------------|------------------------------------------|
| Recall@K | Non | Non (binaire) |
| MRR | Oui (1er seulement) | Non (binaire) |
| nDCG@K | Oui | Oui |

**Exemple concret** :

```
Pertinence par ID: {A: 1.0, B: 0.8, C: 0.5, D: 0.3}
Retrieved: [A, D, B]  (K=3)

DCG@3 = 1.0/log2(2) + 0.3/log2(3) + 0.8/log2(4)
       = 1.0/1 + 0.3/1.58 + 0.8/2
       = 1.0 + 0.19 + 0.4 = 1.59

IDCG@3 (ideal): [A, B, C]
       = 1.0/log2(2) + 0.8/log2(3) + 0.5/log2(4)
       = 1.0 + 0.5 + 0.25 = 1.75

nDCG = 1.59 / 1.75 = 0.91
```

---

## 2. Métriques de Détection

Mesurent la qualité de la détection d'incohérences (classification binaire).

### 2.1 Precision (Précision)

**Définition** : Proportion de prédictions positives qui sont correctes.

**Formule** :

$$\text{Precision} = \frac{TP}{TP + FP}$$

| Élément | Description |
|---------|-------------|
| TP (True Positive) | Incohérence détectée ET réellement présente |
| FP (False Positive) | Incohérence détectée MAIS pas réellement présente |

**Interprétation** :

| Precision | Signification |
|-----------|----------------|
| > 0.90 | Très peu de fausses alertes |
| 0.70 - 0.90 | Bon équilibre |
| < 0.70 | Trop de fausses alarmes |

**Exemple** :
```
Prédit incohérent: 15 documents
Réellement incohérent: 12 documents
TP = 12, FP = 3
Precision = 12 / (12 + 3) = 0.80

→ 80% des alertes étaient vraies
→ 20% étaient des fausses alarmes
```

---

### 2.2 Recall (Rappel)

**Définition** : Proportion des incohérences réelles qui ont été détectées.

**Formule** :

$$\text{Recall} = \frac{TP}{TP + FN}$$

| Élément | Description |
|---------|-------------|
| TP (True Positive) | Incohérence détectée ET réellement présente |
| FN (False Negative) | Incohérence NON détectée MAIS réellement présente |

**Interprétation** :

| Recall | Signification |
|--------|---------------|
| > 0.90 | Presque toutes les incohérences détectées |
| 0.70 - 0.90 | Bonne couverture |
| < 0.70 | Trop d'incohérences manquées |

**Exemple** :
```
Incohérences réelles: 20 documents
Incohérences détectées: 12 documents
TP = 12, FN = 8
Recall = 12 / (12 + 8) = 0.60

→ 60% des incohérences réelles ont été détectées
→ 40% ont été manquées
```

---

### 2.3 F1-Score

**Définition** : Moyenne harmonique de Precision et Recall. Équilibre entre les deux.

**Formule** :

$$\text{F1} = 2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \Recall}$$

**Propriété** : F1 est biaisé vers la valeur la plus basse des deux. Si Precision=0.9 et Recall=0.5, F1=0.64.

**Interprétation** :

| F1 | Niveau |
|----|--------|
| > 0.85 | Excellent |
| 0.70 - 0.85 | Bon |
| 0.50 - 0.70 | Moyen |
| < 0.50 | Faible |

---

### 2.4 Matrice de Confusion

**Définition** : Tableau croisé des prédictions vs réalités.

|  | Prédit: Cohérent | Prédit: Incohérent |
|--|-------------------|---------------------|
| Réel: Cohérent | TN (True Negative) | FP (False Positive) |
| Réel: Incohérent | FN (False Negative) | TP (True Positive) |

**Exemple visuel** :

```
                    Prediction
                 | Incohérent | Cohérent |
    -----------------------------------------
Real  Incohérent  |    12     |    8    |  = 20 (Total incohérents)
     Cohérent     |     3     |   77    |  = 80 (Total cohérents)
    -----------------------------------------
                 |    15    |    85    |  = 100 (Total predictions)

TP = 12, FP = 3, FN = 8, TN = 77

Precision = 12 / 15 = 0.80
Recall = 12 / 20 = 0.60
F1 = 2 × 0.8 × 0.6 / (0.8 + 0.6) = 0.69
```

---

## 3. Métriques Économiques

Mesurent l'efficacité computationnelle et le coût.

### 3.1 Token Count

**Définition** : Nombre de tokens (mots ou sous-mots) dans un texte.

**Implémentation** :

```python
def token_count(text: str) -> int:
    return len(re.findall(r"\S+", text))
```

**Prix typiques (OpenRouter)** :

| Modèle | Input (/1M) | Output (/1M) |
|--------|-------------|--------------|
| Qwen 3.5 8B | $0.10 | $0.30 |
| Claude 3 Haiku | $0.25 | $1.25 |
| GPT-4o Mini | $0.15 | $0.60 |

---

### 3.2 Estimated Cost

**Formule** :

$$\text{Coût} = \frac{\text{prompt\_tokens}}{1000} \times \text{prix\_input} + \frac{\text{completion\_tokens}}{1000} \times \text{prix\_output}$$

**Implémentation** :

```python
def estimate_cost(usage: dict, input_price_per_1k: float, output_price_per_1k: float) -> float:
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    return (prompt_tokens / 1000.0) * input_price_per_1k + \
           (completion_tokens / 1000.0) * output_price_per_1k
```

**Exemple** :

```
Prompt: 1500 tokens → $0.10/1M → $0.00015
Completion: 200 tokens → $0.30/1M → $0.00006
Total: $0.00021

Pour 1000 requêtes: ~$0.21
```

---

### 3.3 Compression Ratio

**Définition** : Ratio de compression du contexte avant appel LLM.

**Formule** :

$$\text{Compression Ratio} = \frac{\text{taille\_compressée}}{\text{taille\_originale}}$$

**Interprétation** :

| Ratio | Signification |
|-------|---------------|
| 0.10 - 0.30 | Compression forte (économique) |
| 0.30 - 0.60 | Compression modérée |
| 0.60 - 1.00 | Faible compression |

**Objectif** : Atteindre un ratio de 0.2-0.3 (comprimer à 20-30% de la taille originale) pour réduire les coûts tout en conservant l'information pertinente.

---

### 3.4 Latency (Latence)

**Définition** : Temps de traitement en millisecondes.

**Composantes typiques** :

| Étape | Latence typique |
|-------|-----------------|
| Détecteurs déterministes | 5-20 ms |
| Recherche sémantique (NextPlaid) | 50-500 ms |
| Appel LLM | 500-5000 ms |
| Pipeline complet | 100-6000 ms |

---

## 4. Métriques de Sévérité

### 4.1 Score de Sévérité

**Définition** : Niveau de gravité agrégé des conflits détectés.

**Pondération par type de conflit** :

| Type de conflit | Poids | Justification |
|-----------------|-------|---------------|
| amount_conflict | 4 | Argent → impact financier direct |
| date_conflict | 3 | Dates → erreurs de planification |
| table_conflict | 3 | Tableaux → données chiffrées |
| reference_mismatch | 2 | Références → traçabilité |
| clause_conflict | 2 | Clauses → risques légaux |
| section_changed | 1 | Section → changement contexte |

**Formule de calcul** :

```python
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

def score_severity(conflicts: list[dict]) -> str:
    if not conflicts:
        return "low"
    
    max_hint = 1
    weighted = 0
    
    for conflict in conflicts:
        hint = conflict.get("severity_hint", "low")
        max_hint = max(max_hint, SEVERITY_RANK.get(hint, 1))
        weighted += _type_weight(conflict.get("type", ""))
    
    if max_hint >= 4 or weighted >= 8:
        return "critical"
    if max_hint >= 3 or weighted >= 5:
        return "high"
    if max_hint >= 2 or weighted >= 2:
        return "medium"
    return "low"
```

**Tableau de décision** :

| Condition | Sévérité |
|-----------|-----------|
| max_hint ≥ 4 OU weighted ≥ 8 | critical |
| max_hint ≥ 3 OU weighted ≥ 5 | high |
| max_hint ≥ 2 OU weighted ≥ 2 | medium |
| Sinon | low |

---

### 4.2 Action Recommandée

| Sévérité | Action recommandée |
|----------|-------------------|
| **critical** | "Block publishing and request immediate manual review." |
| **high** | "Escalate to reviewer before validation." |
| **medium** | "Flag for analyst verification." |
| **low** | "No blocking action required." |

---

## 5. Tableau Récapitulatif

### 5.1 Métriques de Recherche

| Métrique | Domaine | Formule clé | Ideal |
|----------|---------|-------------|-------|
| Recall@K | Pertinence | \|relevant ∩ top-K\| / \|relevant\| | → 1.0 |
| MRR | Classement | 1 / rang(premier hit) | → 1.0 |
| nDCG@K | Classement + pertinence | DCG/IDCG | → 1.0 |

### 5.2 Métriques de Détection

| Métrique | Description | Ideal |
|----------|-------------|-------|
| Precision | TP / (TP + FP) | → 1.0 |
| Recall | TP / (TP + FN) | → 1.0 |
| F1 | 2 × P × R / (P + R) | → 1.0 |

### 5.3 Métriques Économiques

| Métrique | Unité | Idéal |
|----------|-------|-------|
| Tokens | count | ↓ |
| Coût | USD | ↓ |
| Compression Ratio | ratio (0-1) | ↓ (compresser plus) |
| Latence | ms | ↓ |

### 5.4 Métriques de Sévérité

| Niveau | Score ponderé | Action |
|--------|---------------|--------|
| low | 0-1 | No blocking |
| medium | 2-4 | Analyst verification |
| high | 5-7 | Review before validation |
| critical | ≥8 | Block + manual review |

---

## 6. Comment utiliser ces métriques

### 6.1 Pour benchmarker les stratégies de recherche

```json
POST /api/v1/eval/experiments/find
{
  "strategies": ["baseline", "lexical", "semantic", "hybrid"],
  "top_k": 10,
  "max_samples": 100
}
```

Comparer :
- **Recall@K** : Quelle stratégie retrouve le plus de preuves ?
- **MRR** : Quelle stratégie place les preuves en premier ?
- **nDCG@K** : Quelle stratégie classe le mieux les preuves par pertinence ?
- **Latence** : Quelle stratégie est la plus rapide ?

### 6.2 Pour évaluer la détection

```json
POST /api/v1/eval/detection
{
  "gold_labels": [true, false, true, ...],
  "predicted_labels": [true, true, false, ...]
}
```

- **F1 > 0.80** : Prêt pour production
- **F1 0.60-0.80** : Améliorations nécessaires
- **F1 < 0.60** : Pipeline à revoir

### 6.3 Pour optimiser les coûts

Surveiller :
- **avg_compression_ratio** : Doit être < 0.3 pour être économique
- **avg_latency_ms** : Doit être < 500ms pour une bonne UX
- **total_cost_usd** : Suivre par 1000 requêtes

---

## 7. Références

- Métriques IR : [IR Book](https://informationretrieval.org/)
- nDCG : [Wikipedia](https://en.wikipedia.org/wiki/Discounted_cumulative_gain)
- F1-Score : [Wikipedia](https://en.wikipedia.org/wiki/F-score)
