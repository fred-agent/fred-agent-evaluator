# Écrire un dataset d'évaluation (JSON)

**Pour :** l'analyste d'une équipe Fred qui veut évaluer son agent.
**Résultat :** un fichier JSON de questions (± réponses attendues) prêt à lancer une campagne.

> 🇬🇧 English version (canonical): [`write-a-dataset.md`](write-a-dataset.md).
> La documentation de référence est en anglais ; cette version française est une commodité.

Un *dataset* est simplement **une liste de cas**. Un cas = une question posée à
l'agent, et — si vous la connaissez — la réponse de référence. Rien d'autre à écrire :
l'agent produit ses réponses au moment de la campagne, et la plateforme les note.

> C'est le point de départ de toute évaluation. Vous l'écrivez **à la main**, en amont,
> à partir de ce que vous savez du corpus.

---

## Le scénario de référence

Votre équipe a ingéré le corpus **ArxivAi** (une douzaine d'articles arXiv sur l'IA)
et dispose d'un **agent ReAct équipé de l'outil de recherche** sur ce corpus. Vous
voulez vérifier qu'il répond juste, sans halluciner, en s'appuyant sur les documents.

Vous allez donc écrire des questions **dont la réponse se trouve dans le corpus**, et
donner pour chacune la réponse attendue.

---

## Format d'un cas

```jsonc
{
  "input":           "La question posée à l'agent",          // REQUIS
  "expected_output": "La réponse de référence (idéale)",     // optionnel — voir plus bas
  "external_id":     "raguard-objectif",                      // optionnel — votre identifiant lisible
  "tags":            ["rag", "sécurité"]                       // optionnel — pour filtrer/regrouper
}
```

| Champ             | Requis | Rôle |
| ----------------- | :----: | ---- |
| `input`           |   ✅   | Ce que l'agent reçoit. Écrivez-la comme un vrai utilisateur la poserait. |
| `expected_output` |   —    | La réponse de référence. La fournir **débloque plus de métriques** (voir ci-dessous). |
| `external_id`     |   —    | Un identifiant à vous, stable et lisible, pour retrouver le cas dans les résultats. |
| `tags`            |   —    | Étiquettes libres (thème, difficulté…) pour trier vos cas. |

Un dataset est un **tableau JSON de ces cas**.

---

## `minimal` vs `complete` — pourquoi remplir `expected_output`

La plateforme regarde vos cas et en déduit le niveau du dataset :

- **`minimal`** — au moins un cas n'a pas d'`expected_output`. Seules les métriques
  « sans référence » s'appliquent (fidélité, pertinence de la réponse, hallucination…).
- **`complete`** — **tous** les cas ont un `expected_output`. Toutes les métriques
  deviennent disponibles, y compris celles qui comparent à la référence
  (*Contextual Precision*, *Contextual Recall*).

| Vous fournissez `expected_output` ? | Niveau     | Métriques débloquées en plus                     |
| ----------------------------------- | ---------- | ------------------------------------------------- |
| Non (ou partiellement)              | `minimal`  | —                                                 |
| Oui, sur **tous** les cas           | `complete` | *Contextual Precision*, *Contextual Recall*       |

> Le niveau est **toujours dérivé de vos cas**, jamais déclaré. Il suffit d'un cas sans
> réponse attendue pour retomber en `minimal`. Détail dans
> [`../rfc/EVAL-DATASET-RFC.md`](../rfc/EVAL-DATASET-RFC.md) (§9, matrice métriques → champs requis).

`expected_output` est une **réponse de référence**, pas une chaîne à retrouver mot pour
mot : le juge compare le sens, pas les caractères.

---

## Exemple complet — corpus ArxivAi

`arxiv-ai-eval.json` — six cas `complete`, chacun répondable depuis un article du corpus :

```json
[
  {
    "external_id": "raguard-objectif",
    "input": "Quel problème l'approche RAGuard cherche-t-elle à résoudre ?",
    "expected_output": "Rendre la génération augmentée par récupération (RAG) plus sûre lorsque le contexte récupéré contient des passages trompeurs ou malveillants, en filtrant/neutralisant ces passages avant qu'ils n'influencent la réponse du LLM.",
    "tags": ["rag", "sécurité"]
  },
  {
    "external_id": "policymaking-eval",
    "input": "Que cherche à mesurer l'étude « What Would an LLM Do? » sur les LLM ?",
    "expected_output": "Les capacités des grands modèles de langage en matière de conception de politiques publiques (policymaking) : leur aptitude à raisonner et proposer des décisions de politique publique.",
    "tags": ["évaluation", "gouvernance"]
  },
  {
    "external_id": "mcp-medical",
    "input": "Quel protocole le framework agentique de standardisation de concepts médicaux utilise-t-il ?",
    "expected_output": "Le Model Context Protocol (MCP), employé dans une architecture agentique pour normaliser des concepts médicaux.",
    "tags": ["agent", "santé"]
  },
  {
    "external_id": "fama-marketplace",
    "input": "Sur quel type de marché l'assistant FaMA est-il conçu pour opérer ?",
    "expected_output": "Une marketplace de particulier à particulier (consumer-to-consumer, C2C), où FaMA agit comme assistant agentique animé par un LLM.",
    "tags": ["agent", "e-commerce"]
  },
  {
    "external_id": "planning-infinite-domains",
    "input": "Quelle méthode de recherche est proposée pour gérer des paramètres de domaine infinis en planification ?",
    "expected_output": "Une recherche best-first avec expansions partielles différées (Best-First Search with Delayed Partial Expansions).",
    "tags": ["planification"]
  },
  {
    "external_id": "cot-space",
    "input": "Que propose le cadre CoT-Space ?",
    "expected_output": "Un cadre théorique pour le « slow-thinking » interne des LLM, formalisé via l'apprentissage par renforcement.",
    "tags": ["raisonnement", "théorie"]
  }
]
```

Variante **`minimal`** : retirez les `expected_output`. Utile pour un premier passage
rapide, quand vous voulez juste voir si l'agent hallucine ou reste fidèle au corpus,
sans encore rédiger les réponses de référence.

---

## Écrire de bonnes questions

- **Répondable depuis le corpus.** L'agent doit pouvoir trouver la réponse via son
  outil de recherche. Une question hors corpus mesure surtout sa capacité à dire « je
  ne sais pas ».
- **Une intention par cas.** Évitez les questions à tiroirs ; elles rendent le score
  ambigu.
- **Formulez comme un utilisateur réel.** C'est ce que l'agent verra en production.
- **Réponse de référence concise et factuelle.** Le sens compte, pas la longueur ni la
  formulation exacte.
- **Couvrez plusieurs documents.** Un cas par article évite un dataset biaisé vers un
  seul sujet. Servez-vous des `tags` pour vérifier l'équilibre.
- **10–30 cas** suffisent pour un premier signal fiable ; inutile d'en écrire des
  centaines pour démarrer.

---

## Et ensuite ? — de votre fichier aux résultats

Deux étapes, deux objets. D'abord **enregistrer** vos cas comme une **evaluation** : la
définition immuable et versionnée. Vous la nommez ; le serveur attribue la version.

```jsonc
POST /evaluation/v1/evaluations      // → 201, renvoie evaluation_id (+ version, completeness)
{
  "team_id": "<votre équipe>",
  "name": "ArxivAi — jeu analyste",
  "origin": "upload",
  "source_filename": "arxiv-ai-eval.json",
  "cases": [ /* … le contenu de votre fichier … */ ]
}
```

Puis démarrer un **run** : une exécution de cette evaluation contre un agent cible. Le
serveur possède le profil de scoring, le juge et les valeurs par défaut de concurrence —
vous ne choisissez que l'agent.

```jsonc
POST /evaluation/v1/evaluations/{evaluation_id}/runs   // → 202, renvoie run_id
{
  "team_id": "<votre équipe>",
  "target": { "kind": "managed_instance", "agent_instance_id": "<instance>" }
}
```

- **Evaluation vs run :** l'evaluation s'écrit une fois ; chaque exécution est un
  nouveau run. Ré-exécuter n'écrase jamais les résultats précédents — c'est ainsi que
  l'on compare deux versions d'un agent sur les mêmes questions.
- La cible est uniquement une **instance d'agent managée** (EVAL-04) ; un couple
  `runtime_id`/`agent_id` nu n'est plus accepté à la création.
- Le mode RAG est détecté automatiquement dès que l'agent renvoie un contexte récupéré :
  vous n'avez rien à configurer côté métriques.
- Suivi et lecture des scores : [`evaluate-an-agent.md`](evaluate-an-agent.md).
- Le contrat d'API complet (routes, statuts) est dans
  [`../DEVELOPER_CONTRACT.md`](../DEVELOPER_CONTRACT.md).

---

## Checklist avant de lancer

- [ ] Chaque cas a un `input` non vide.
- [ ] Les questions sont répondables depuis le corpus ingéré.
- [ ] Pour viser `complete` : **tous** les cas ont un `expected_output`.
- [ ] Les `external_id` sont uniques et lisibles (vous les retrouverez dans les résultats).
- [ ] Le JSON est valide (un tableau d'objets).
