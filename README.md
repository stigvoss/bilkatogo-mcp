# bilkatogo-mcp

Unofficial, single-user MCP server for BilkaToGo (streamable HTTP, `/mcp`), protected by an API key.

- The Bilka account is fixed by config. It logs in with a pasted Gigya `login_token`, with
  email + password, or both; each is optional.
- The last working token is remembered in `/data/session.json` (a volume), so the credentials can
  be removed from the config after the first successful login.
- Clients send `Authorization: Bearer <MCP_API_KEY>`.
- `/healthz` is unauthenticated (for container and reverse-proxy health checks).

## Docker

The image is published to GHCR by CI on every push to `main` and is public, so no login is needed to pull it.

    docker run -d --name bilkatogo-mcp --restart unless-stopped \
      --read-only --cap-drop ALL --security-opt no-new-privileges:true \
      -p 127.0.0.1:8000:8000 -v bilkatogo-data:/data \
      -e MCP_API_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" \
      -e BILKATOGO_LOGIN_TOKEN="<localStorage.getItem(\"auth\") from bilkatogo.dk>" \
      -e BILKATOGO_ALLOWED_HOSTS="bilka-mcp.example.com" \
      ghcr.io/stigvoss/bilkatogo-mcp:latest

Note the generated key (`docker inspect` shows it, and so does the login token; use `-e MCP_API_KEY_FILE`
and `-e BILKATOGO_LOGIN_TOKEN_FILE` with mounted files to avoid that). The server is then at
`http://127.0.0.1:8000/mcp`, with an unauthenticated `/healthz`. To build locally instead:
`docker build -t bilkatogo-mcp .` and use that image name.

## Docker Compose (behind a reverse proxy)

Streamable HTTP at `/mcp`. A minimal `compose.yaml` (the one in this repo is the same, with comments
and the optional email/password secrets):

```yaml
services:
  bilkatogo-mcp:
    image: ghcr.io/stigvoss/bilkatogo-mcp:latest
    restart: unless-stopped
    user: "${PUID:-10001}:${PGID:-10001}"   # run as the secret files' owner
    environment:
      BILKATOGO_ALLOWED_HOSTS: "bilka-mcp.example.com"   # public hostname of the proxy route
      MCP_API_KEY_FILE: /run/secrets/mcp_api_key
      BILKATOGO_LOGIN_TOKEN_FILE: /run/secrets/bilkatogo_login_token
    secrets:
      - mcp_api_key
      - bilkatogo_login_token
    volumes:
      - bilkatogo-data:/data
    networks:
      - proxy
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - "no-new-privileges:true"

volumes:
  bilkatogo-data:

secrets:
  mcp_api_key:
    file: ./secrets/mcp_api_key
  bilkatogo_login_token:
    file: ./secrets/bilkatogo_login_token

networks:
  proxy:
    external: true
    name: ${PROXY_NETWORK:-proxy}   # the Docker network your reverse proxy or tunnel is on
```

1. Create the secrets (they stay out of the image and out of `docker inspect`) and tell Compose to
   run the container as the files' owner, so they can stay private (`600`) instead of being made
   readable to everyone:

       mkdir -p secrets
       python3 -c "import secrets;print(secrets.token_urlsafe(32))" > secrets/mcp_api_key
       # paste the token from the browser console: localStorage.getItem("auth")
       pbpaste > secrets/bilkatogo_login_token
       chmod 600 secrets/*
       printf 'PUID=%s\nPGID=%s\n' "$(id -u)" "$(id -g)" > .env

   See [Creating the login secret files](#creating-the-login-secret-files) for Linux, the optional
   email + password login and replacing a token.

   If you created the `bilkatogo-data` volume before this setting existed, it is owned by uid 10001
   and the saved session can't be written: recreate it (`docker volume rm bilkatogo-data`) or run
   `docker run --rm -v bilkatogo-data:/data alpine chmod 1777 /data` once.
2. Edit `compose.yaml`: set `BILKATOGO_ALLOWED_HOSTS` to your public hostname, and make sure the
   container shares a Docker network with your reverse proxy or tunnel (`PROXY_NETWORK`, default
   `proxy`; create it with `docker network create proxy` or point it at an existing one).
3. `docker compose pull && docker compose up -d`. To build locally instead, replace `image:` with `build: .`.
4. Point your reverse proxy or tunnel at `http://bilkatogo-mcp:8000` and terminate TLS there. If the
   proxy has its own login (SSO, basic auth, a PIN page), turn it off for this route: those are
   browser flows that MCP clients can't complete, and this server checks the API key itself.
5. Claude Code. Keep the key out of shell history and plain-text config by using an environment
   variable (Claude Code expands `${VAR}` in MCP server config; check with `claude mcp get bilkatogo` that the header shows as expected):

       export BILKATOGO_MCP_KEY="$(cat secrets/mcp_api_key)"    # e.g. from your shell profile
       claude mcp add-json bilkatogo '{"type":"http","url":"https://bilka-mcp.example.com/mcp","headers":{"Authorization":"Bearer ${BILKATOGO_MCP_KEY}"}}'

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BILKATOGO_LOGIN_TOKEN` / `_FILE` | optional | Gigya login_token pasted from the browser |
| `BILKATOGO_EMAIL` / `_FILE`, `BILKATOGO_PASSWORD` / `_FILE` | optional | Enables automatic re-login when the token is rejected |
| `BILKATOGO_STATE_FILE` | `/data/session.json` | Where the working token is remembered |
| `MCP_API_KEY` / `_FILE` | required | API key clients must send (min 24 chars) |
| `BILKATOGO_ALLOWED_HOSTS` | localhost only | Comma-separated Host headers to accept |
| `BILKATOGO_ALLOWED_ORIGINS` | localhost only | Comma-separated allowed Origins (browser clients) |
| `BILKATOGO_STORE_ID` | `1666` | Store id (Bilka Sønderborg) that search results are filtered by; see [Finding your store ID](#finding-your-store-id) |
| `BILKATOGO_MAX_QUANTITY` | `20` | Largest quantity a single cart call may set |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxy addresses whose `X-Forwarded-*` headers are trusted |
| `RATE_LIMIT_PER_MIN` | `120` | Global request limit |
| `AUTH_FAIL_LIMIT_PER_MIN` | `10` | Failed-auth attempts per minute before everything is refused for a while |

### Creating the login secret files

The secrets are plain files in `secrets/` that Compose mounts into the container (the `*_FILE`
variables). You need the API key and at least one Bilka login: a pasted token, email + password, or
both. They are the keys to your Bilka account, so keep them out of chat, issues and git (`secrets/` and
`.env` are already in `.gitignore`).

    mkdir -p secrets && chmod 700 secrets

The API key that clients send (at least 24 characters):

    python3 -c "import secrets;print(secrets.token_urlsafe(32))" > secrets/mcp_api_key

The Bilka login token. Sign in on bilkatogo.dk, open the browser's developer console and run
`localStorage.getItem("auth")`. Copy the value without the surrounding quotes, then save it from the
clipboard (`pbpaste` on macOS, `xclip -selection clipboard -o` on Linux) or type it at a hidden prompt:

    pbpaste > secrets/bilkatogo_login_token
    printf 'Token: '; IFS= read -rs token; echo; printf '%s' "$token" > secrets/bilkatogo_login_token; unset token

Optionally your email and password, which let the server log in again by itself when the token
expires:

    printf '%s' 'you@example.com' > secrets/bilkatogo_email
    printf 'Password: '; IFS= read -rs pw; echo; printf '%s' "$pw" > secrets/bilkatogo_password; unset pw

The email and password are commented out in `compose.yaml`; to use them, uncomment the three places
that mention `bilkatogo_email` and `bilkatogo_password` (the `BILKATOGO_*_FILE` variables, the
service's `secrets:` list and the top-level `secrets:`). Then make the files private and let the
container read them by running it as their owner:

    chmod 600 secrets/*
    printf 'PUID=%s\nPGID=%s\n' "$(id -u)" "$(id -g)" > .env

Leading and trailing whitespace in a file is ignored. Check that the login works with
`docker compose run --rm bilkatogo-mcp python server.py --check-login` (see below). To replace a token
later, overwrite the file and delete the saved session so the new one is used:

    docker compose run --rm bilkatogo-mcp rm /data/session.json

At least one login source is needed the first time (token, or email + password). Order tried:
saved token, then `BILKATOGO_LOGIN_TOKEN`, then email/password. If all fail, the tools return an
error saying so.

### Finding your store ID

`search_products` only returns products that the store is stocking and selling, so set
`BILKATOGO_STORE_ID` to the store you order from. The default, `1666`, is Bilka Sønderborg. The ID is
the `sid` of a pickup place, and the list of them needs no login:

    curl -s "https://api.bilkatogo.dk/api/shop/v6/AvailableDeliveryAddresses?u=w&orderByZipcode=1" \
      | python3 -c 'import sys,json; [print(a["sid"], a["name"]) for a in json.load(sys.stdin)["addresses"]]' | sort -u

Pick the line for your store, for example `1662 Bilka Kolding`. Some pickup points share the ID of the
store they are served from (`Pickup Fredericia` is also `1662`). This is an unofficial endpoint and the
list can change.

### Log in once, then remove the credentials

    docker compose run --rm bilkatogo-mcp python server.py --check-login

Prints `OK: authenticated via …` or `FAILED: …` (never a secret) and saves the token to the data
volume. After that you can remove the email/password (or token) secrets from `compose.yaml` and
`secrets/`. If the saved token later expires and no credentials are configured, provide a fresh
token or credentials again. The password, if you configure one, sits in `secrets/`; use a
password you don't reuse elsewhere.

Tools: search_products, get_cart, set_cart_quantity, add_to_cart, clear_cart, list_orders,
get_order, get_favourites, get_delivery_date. No checkout.

Local run without Docker: `BILKATOGO_LOGIN_TOKEN=… MCP_API_KEY=… uv run --python 3.12 server.py`

## Security notes

- Product, cart and order text comes from Bilka and is untrusted; tool descriptions tell the model
  not to follow instructions found in it. `clear_cart` should only run after explicit confirmation.
- `list_orders`, `get_order` and `get_delivery_date` return trimmed data (no name, address, door or pickup codes).
- The Bilka session can do more than these tools: treat `secrets/`, the `bilkatogo-data` volume and
  its backups like a password. Use a password you don't reuse.
- Every container on the shared proxy network can reach this server; prefer a network shared only
  with the proxy.
- The failed-auth limiter is global: repeated bad keys can lock you out for up to a minute.
- The image installs exactly what `uv.lock` pins (`uv sync --locked`), and both base images are
  pinned by digest. Dependabot opens weekly PRs for Python packages, Docker images and GitHub
  Actions; CI (`.github/workflows/ci.yml`) runs lint, tests and a container smoke test on each, and
  publishes the image to `ghcr.io/stigvoss/bilkatogo-mcp` from `main`.

## Development

    uv sync                 # installs runtime + dev dependencies
    uv run ruff check .
    uv run pytest
