# Postman - Tests Manuels Classés

## Fichiers

- `Backend-Regex-Manual-Tests.postman_collection.json`
- `Backend-Regex-Local.postman_environment.json`

## Import

1. Ouvre Postman.
2. Importe la collection.
3. Importe l'environment.
4. Active l'environment `Backend Regex Local`.

## Ordre d'exécution recommandé

1. `00 - Setup`
2. `01 - Health & Info`
3. `02 - Documents` (Upload puis Status/Content)
4. `03 - Search`
5. `04 - Detection`
6. `05 - LLM`
7. `06 - Evaluation (Phase 7)`
8. `07 - Error Cases`

## Variables importantes

- `base_url` (environment): `http://localhost:8000`
- `document_id` (collection variable): rempli automatiquement après Upload
- `index_name`: `contracts`
- `llm_model`: modèle OpenRouter à tester

## Notes

- Pour `Upload Document`, sélectionne un vrai fichier dans le champ `file`.
- Pour le test d'erreur extension non supportée, upload un `.txt`.
