# FOG-MCP
An MCP server proof of concept for FOG 1.6

Serveur MCP (stdio) pour piloter un serveur [FOG Project](https://fogproject.org) via son API REST.
Cible : **FOG 1.6.0-RC-10** (spec OpenAPI 3.0.3 de référence : [`swagger.json`](swagger.json)).

- Python ≥ 3.11, géré avec [uv](https://docs.astral.sh/uv/)
- SDK MCP officiel `mcp` 2.x : `MCPServer` (nouveau nom de `FastMCP` depuis mcp 2.0, même API à décorateurs)
- Client HTTP `httpx`, tests `pytest` + `respx`

## Outils

**Lecture** (toujours disponibles)

| Outil | Endpoint FOG |
|---|---|
| `system_info` | `GET /system/info` (sans authentification) + `GET /task/count` pour vérifier le token |
| `search_hosts(query, limit, start)` | `GET /host/search/{item}` |
| `get_host(host_id)` | `GET /host/{id}` |
| `list_images(limit, start, name_filter)` | `GET /image` (`?filter=name=…`) |
| `list_groups(limit, start)` | `GET /group` |
| `current_tasks(limit, start)` | `GET /task/current` |
| `multicast_sessions(active_only, limit, start)` | `GET /multicastsession/current` ou `GET /multicastsession` |

**Écriture** (enregistrés seulement si `FOG_MCP_ALLOW_WRITE=1`)

| Outil | Endpoint FOG |
|---|---|
| `assign_image(host_id, image_id, confirm)` | `PUT /host/{id}` avec `{"imageID": …}` |
| `create_task(target, target_id, task_type_id, confirm, shutdown, wol, debug, deploy_snapins, task_name)` | `POST /host/{id}/task` ou `POST /group/{id}/task` |
| `cancel_task(task_id \| host_id \| group_id, confirm)` | `DELETE /task/{id}/cancel`, `/host/{id}/cancel` ou `/group/{id}/cancel` |

### Sécurité

- **Lecture seule par défaut** : sans `FOG_MCP_ALLOW_WRITE=1`, les outils d'écriture n'existent pas du tout.
- **Toute écriture se fait en deux temps.** Sans `confirm=true`, l'outil ne fait que des lectures
  et renvoie `status: "confirmation_required"` avec un récapitulatif :
  - hôte (nom, MAC, image actuelle) ou groupe (nombre d'hôtes, liste, hôtes sans image) ;
  - type de tâche, avec le nom lu sur le serveur via `GET /tasktype/{id}` ;
  - options, plus des avertissements.

  Le même appel avec `confirm=true` exécute l'action.
- **Types destructifs** : ils sont signalés dans le récapitulatif (`destructive: true` + avertissement).
  - La spec ne liste pas les IDs de types de tâche (ils viennent de la table `taskTypes` du serveur).
  - La liste par défaut reprend donc les IDs standard de FOG : `1,2,8,15,16,17,18,19,20`
    (deploy, capture, multicast, variantes debug, wipes). Elle se change avec `FOG_MCP_DESTRUCTIVE_TASK_TYPES`.
  - En plus, tout type dont le nom contient deploy, wipe, multicast ou capture est traité comme destructif.
- Un type de tâche inconnu (404) ou incompatible avec la cible (`access` = host/group) est refusé avant tout POST.
- Les champs sensibles (`ADPass`, `ADUser`, `productKey`, `token`, `sec_tok`, `pub_key`…) sont retirés de toutes les réponses.
- Une annulation impossible (409 : tâche déjà terminée) renvoie `status: "not_cancellable"` au lieu d'une erreur brute.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `FOG_URL` | *(obligatoire)* | URL de base **avec** le préfixe `/fog`, ex. `https://fog.example.lan/fog` |
| `FOG_API_TOKEN` | *(obligatoire)* | Token `fog_…` créé dans l'onglet API d'un utilisateur ; envoyé tel quel en `Authorization: Bearer` |
| `FOG_CA_BUNDLE` | – | Fichier PEM de la CA qui a signé le certificat FOG (auto-signé) |
| `FOG_VERIFY_TLS` | `1` | `0` désactive la vérification TLS (à éviter ; ignoré si `FOG_CA_BUNDLE` est défini) |
| `FOG_MCP_ALLOW_WRITE` | `0` | `1` enregistre les outils d'écriture |
| `FOG_MCP_DESTRUCTIVE_TASK_TYPES` | `1,2,8,15,16,17,18,19,20` | IDs de types de tâche signalés comme destructifs |
| `FOG_TIMEOUT` | `30` | Timeout HTTP (secondes) |

Pour récupérer le certificat auto-signé du serveur FOG :

```bash
openssl s_client -connect fog.example.lan:443 -showcerts </dev/null 2>/dev/null \
  | openssl x509 -outform PEM > ~/fog-ca.pem
```

> Si FOG utilise sa propre CA (`/opt/fog/snapins/ssl/CA/.fogCA.pem`), c'est ce fichier-là qu'il faut fournir.

## Installation et tests

```bash
uv sync
uv run pytest            # 41 tests, toutes les réponses HTTP sont simulées avec respx
```

Lancement manuel (stdio ; les logs vont sur stderr) :

```bash
FOG_URL=https://fog.example.lan/fog FOG_API_TOKEN=fog_xxx uv run fog-mcp
```

## Tester avec MCP Inspector

```bash
npx @modelcontextprotocol/inspector \
  -e FOG_URL=https://fog.example.lan/fog \
  -e FOG_API_TOKEN=fog_xxx \
  -e FOG_CA_BUNDLE=$HOME/fog-ca.pem \
  uv --directory /chemin/absolu/FOG-MCP run fog-mcp
```

Ouvre l'URL affichée (avec son token de session), puis **Connect** et **Tools → List Tools** :

1. `system_info` : vérifie `server.version` et `auth: "ok"`.
2. `search_hosts` avec `query=pc`, puis `get_host` sur un ID trouvé.
3. Pour tester l'écriture, ajoute `-e FOG_MCP_ALLOW_WRITE=1` et relance.
   - `create_task` sans `confirm` doit renvoyer `confirmation_required` sans rien créer.
   - Vérifie dans l'interface FOG qu'aucune tâche n'a été créée.
   - Un test sans risque : le type 14 (wake-up) avec `confirm=true`.

## Enregistrer dans Claude Code

```bash
# lecture seule, disponible dans tous les projets
claude mcp add --scope user --transport stdio \
  -e FOG_URL=https://fog.example.lan/fog \
  -e FOG_API_TOKEN=fog_xxx \
  -e FOG_CA_BUNDLE=$HOME/fog-ca.pem \
  fog -- uv --directory /chemin/absolu/FOG-MCP run fog-mcp

claude mcp list          # doit afficher "fog ... ✓ Connected"
```

Pour activer l'écriture, ajoute `-e FOG_MCP_ALLOW_WRITE=1`. Le plus simple est de supprimer puis réenregistrer le serveur
(`claude mcp remove fog --scope user`).

> Les variables passées avec `-e` sont stockées en clair dans `~/.claude.json`.
> Mieux vaut un token dédié à cette intégration (FOG permet d'en avoir plusieurs, révocables un par un),
> attaché à un utilisateur FOG aux droits limités.

Dans Claude Code, `/mcp` affiche l'état du serveur et ses outils.

## Arborescence

```
src/fog_mcp/
  config.py       variables d'environnement, contexte TLS
  client.py       client httpx : Bearer, pagination start/length, erreurs, nettoyage des secrets
  shapes.py       réduction des objets FOG aux champs utiles
  tasks.py        types de tâche, détection destructive, récapitulatifs hôte/groupe
  tools_read.py   outils de lecture
  tools_write.py  outils d'écriture (confirm obligatoire)
  server.py       MCPServer, enregistrement conditionnel, transport stdio
tests/            tests respx + client MCP en mémoire
```
