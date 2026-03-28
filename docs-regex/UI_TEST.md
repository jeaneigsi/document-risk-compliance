Parfait. Là on va sortir les gants de boxe.

Le but n’est plus de tester si le système sait retrouver une info évidente. Le but est de créer des claims **extrêmement piégeux**, qui forcent ton application à bien distinguer :

* ce qui est explicitement dit,
* ce qui est seulement suggéré,
* ce qui est faux par glissement subtil,
* et ce qui est plausible mais non supporté.

Je vais te proposer 10 tests **très durs**, avec un niveau bien plus élevé. Je te donne le claim, le label attendu, puis pourquoi il est redoutable.

---

## Test 1 — glissement sémantique sur la recommandation de formation

**Claim**
La formation recommandée est un master spécialisé en conception matérielle, en architecture des ordinateurs ou en systèmes embarqués, l’informatique n’étant citée qu’indirectement.

**Label attendu**
**Faux**

**Pourquoi c’est dur**
Le claim sonne presque juste, parce que “architecture des ordinateurs” et “systèmes embarqués” sont bien présents. Mais le texte dit explicitement :

**Master en architecture des ordinateurs, systèmes embarqués ou informatique**

Donc “informatique n’étant citée qu’indirectement” est faux.

**Ce que ça teste**
La capacité à repérer une falsification subtile à l’intérieur d’une phrase globalement crédible.

---

## Test 2 — mélange vrai/faux dans la méthodologie

**Claim**
La thèse vise à générer automatiquement des simulateurs exécutables à partir de spécifications, mais la cohérence avec les modèles formels est laissée aux outils de vérification en aval.

**Label attendu**
**Faux**

**Pourquoi c’est dur**
La première partie est correcte. Le piège est dans la seconde. Le texte dit précisément que la méthodologie doit produire :

**des modèles exécutables et des modèles formels cohérents**

Donc la cohérence n’est pas “laissée en aval”, elle fait partie du cœur du sujet.

**Ce que ça teste**
La détection de contradiction partielle dans un claim composite.

---

## Test 3 — abus d’inférence à partir de RISC-V

**Claim**
Le sujet de thèse porte principalement sur la génération de modèles pour processeurs RISC-V.

**Label attendu**
**Non supporté** ou **Faux** selon ton protocole

**Pourquoi c’est dur**
Le texte cite bien :

**les processeurs RISC-V ou les accélérateurs matériels**

mais comme exemples de systèmes matériels modernes, pas comme cible exclusive ou principale.

**Ce que ça teste**
La capacité à ne pas transformer un exemple illustratif en objet central du sujet.

---

## Test 4 — inversion du rôle de la validation

**Claim**
L’objectif principal de la thèse est de prouver formellement la correction des architectures matérielles elles-mêmes.

**Label attendu**
**Faux**

**Pourquoi c’est dur**
Le texte parle de fiabilité, sécurité, vérification formelle et correction, donc ce claim semble plausible. Mais le sujet ne dit pas qu’il faut prouver formellement le matériel réel lui-même. Il parle surtout de :

* générer des modèles fonctionnels et formels,
* augmenter la confiance dans leur correction.

C’est très différent.

**Ce que ça teste**
La distinction entre **vérifier le matériel réel** et **générer des modèles corrects du matériel**.

---

## Test 5 — glissement sur la boucle de retour

**Claim**
La méthodologie repose sur des boucles de retour provenant uniquement des outils de simulation, l’apprentissage par renforcement jouant un rôle de validation secondaire.

**Label attendu**
**Faux**

**Pourquoi c’est dur**
Le texte dit :

**boucles de retour issues des outils de simulation et de vérification formelle, combinées à des techniques d’apprentissage par renforcement**

Le claim déforme cette triple combinaison en supprimant une source et en rétrogradant le RL.

**Ce que ça teste**
La capacité à vérifier une relation logique entre plusieurs composantes méthodologiques.

---

## Test 6 — claim très plausible mais trop spécifique

**Claim**
Le doctorant devra produire à la fois un simulateur fonctionnel, un modèle de vérification formelle et un compilateur de test pour les spécifications étudiées.

**Label attendu**
**Non supporté**

**Pourquoi c’est dur**
Le simulateur fonctionnel et le modèle formel sont cohérents avec le texte. Le “compilateur de test” paraît très plausible dans ce domaine, mais il n’est jamais mentionné.

**Ce que ça teste**
La résistance à l’hallucination plausible.

---

## Test 7 — confusion fine sur les résultats attendus

**Claim**
Les résultats attendus incluent une réduction de l’effort de modélisation manuelle et une validation sur des cas d’étude réalistes, mais le texte ne mentionne pas explicitement une amélioration de la cohérence entre modèles.

**Label attendu**
**Faux**

**Pourquoi c’est dur**
Le claim est presque correct, mais le texte dit explicitement :

**une meilleure cohérence entre les différents modèles**

Donc la dernière partie est fausse.

**Ce que ça teste**
La vérification précise d’une négation ciblée sur un détail important.

---

## Test 8 — jeu de rôle institutionnel

**Claim**
Le chercheur à contacter et le directeur de thèse appartiennent au même environnement CEA/DSCIN/LECA, mais leurs coordonnées de contact ne sont pas identiques.

**Label attendu**
**Vrai**

**Pourquoi c’est dur**
Il faut agréger plusieurs fragments :

* les deux sont au CEA,
* les deux sont liés à DSCIN/LECA,
* leurs numéros et emails diffèrent.

C’est simple pour un humain, mais ça demande une bonne fusion d’évidence.

**Ce que ça teste**
L’agrégation multi-fragments sans confusion.

---

## Test 9 — contradiction implicite sur la nature du travail

**Claim**
Le sujet cherche surtout à remplacer complètement les outils de simulation et de vérification formelle par des LLM.

**Label attendu**
**Faux**

**Pourquoi c’est dur**
Le texte donne beaucoup de place aux LLM, donc un système naïf pourrait conclure à un remplacement. En réalité, les outils de simulation et de vérification formelle restent dans la boucle comme sources de feedback.

**Ce que ça teste**
La capacité à distinguer **automatiser avec** de **remplacer entièrement par**.

---

## Test 10 — claim extrêmement piégeux sur le niveau de confiance

**Claim**
La thèse ne promet pas une preuve absolue de correction, mais cherche à augmenter la confiance dans la correction des modèles générés.

**Label attendu**
**Vrai**

**Pourquoi c’est dur**
C’est un claim de très haut niveau, presque philosophique, mais il colle précisément au texte :

**tout en augmentant la confiance dans leur correction**

Beaucoup de systèmes faibles vont hésiter parce que ce n’est pas une copie mot à mot.

**Ce que ça teste**
La compréhension sémantique fine, sans dépendre du lexical brut.

---

# Les 5 plus violents pour départager les systèmes

Si ton objectif est vraiment de “voir qui ressort vainqueur”, je te conseille surtout ces 5-là :

**Test 2**
Parce qu’il combine une moitié vraie et une moitié fausse.

**Test 3**
Parce qu’il force à distinguer exemple et objet principal.

**Test 5**
Parce qu’il teste la composition logique de la méthodologie.

**Test 6**
Parce qu’il ressemble énormément à une vérité technique plausible.

**Test 10**
Parce qu’il exige une vraie compréhension sémantique, pas du simple matching.

---

# Version prête pour ton benchmark

Je te donne aussi une structure JSON que tu peux injecter directement dans ton évaluation :

```json
[
  {
    "id": "hard_01",
    "claim": "La formation recommandée est un master spécialisé en conception matérielle, en architecture des ordinateurs ou en systèmes embarqués, l’informatique n’étant citée qu’indirectement.",
    "expected_label": "false",
    "difficulty": "hard"
  },
  {
    "id": "hard_02",
    "claim": "La thèse vise à générer automatiquement des simulateurs exécutables à partir de spécifications, mais la cohérence avec les modèles formels est laissée aux outils de vérification en aval.",
    "expected_label": "false",
    "difficulty": "hard"
  },
  {
    "id": "hard_03",
    "claim": "Le sujet de thèse porte principalement sur la génération de modèles pour processeurs RISC-V.",
    "expected_label": "not_supported",
    "difficulty": "hard"
  },
  {
    "id": "hard_04",
    "claim": "L’objectif principal de la thèse est de prouver formellement la correction des architectures matérielles elles-mêmes.",
    "expected_label": "false",
    "difficulty": "hard"
  },
  {
    "id": "hard_05",
    "claim": "La méthodologie repose sur des boucles de retour provenant uniquement des outils de simulation, l’apprentissage par renforcement jouant un rôle de validation secondaire.",
    "expected_label": "false",
    "difficulty": "hard"
  },
  {
    "id": "hard_06",
    "claim": "Le doctorant devra produire à la fois un simulateur fonctionnel, un modèle de vérification formelle et un compilateur de test pour les spécifications étudiées.",
    "expected_label": "not_supported",
    "difficulty": "hard"
  },
  {
    "id": "hard_07",
    "claim": "Les résultats attendus incluent une réduction de l’effort de modélisation manuelle et une validation sur des cas d’étude réalistes, mais le texte ne mentionne pas explicitement une amélioration de la cohérence entre modèles.",
    "expected_label": "false",
    "difficulty": "hard"
  },
  {
    "id": "hard_08",
    "claim": "Le chercheur à contacter et le directeur de thèse appartiennent au même environnement CEA/DSCIN/LECA, mais leurs coordonnées de contact ne sont pas identiques.",
    "expected_label": "true",
    "difficulty": "hard"
  },
  {
    "id": "hard_09",
    "claim": "Le sujet cherche surtout à remplacer complètement les outils de simulation et de vérification formelle par des LLM.",
    "expected_label": "false",
    "difficulty": "hard"
  },
  {
    "id": "hard_10",
    "claim": "La thèse ne promet pas une preuve absolue de correction, mais cherche à augmenter la confiance dans la correction des modèles générés.",
    "expected_label": "true",
    "difficulty": "hard"
  }
]
```

# Ce que je te conseille en plus

Ne mélange pas tous les tests dans un seul sac. Fais 3 niveaux :

* **easy** : extraction factuelle directe
* **medium** : reformulation + multi-fragments
* **hard** : contradiction partielle, non-supporté plausible, glissement sémantique

Comme ça, tu verras non seulement quel moteur gagne, mais **où** il gagne.

La suite la plus utile maintenant, c’est que je te propose **10 tests encore plus cruels**, cette fois sous forme de claims presque juridiques, très longs, très ambigus, conçus pour faire trébucher même un bon système.
