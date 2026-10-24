# bilkatogo-mcp

Unofficial, single-user MCP server for BilkaToGo (streamable HTTP, `/mcp`), protected by an API key.

- The Bilka account is fixed by config. It logs in with a pasted Gigya `login_token`, with
  email + password, or both; each is optional.
- The last working token is remembered in `/data/session.json` (a volume), so the credentials can
  be removed from the config after the first successful login.
- Clients send `Authorization: Bearer <MCP_API_KEY>`.
- `/healthz` is unauthenticated (for Docker/Pangolin health checks).

## Docker Compose (behind Pangolin / newt)

1. Create the secrets (they stay out of the image and out of `docker inspect`):

       mkdir -p secrets
       python3 -c "import secrets;print(secrets.token_urlsafe(32))" > secrets/mcp_api_key
       # paste the token from the browser console: localStorage.getItem("auth")
       pbpaste > secrets/bilkatogo_login_token
       chmod 600 secrets/*

2. Edit `compose.yaml`: set `BILKATOGO_ALLOWED_HOSTS` to your public hostname and the `newt`
   network name to the Docker network your newt container is on.
3. `docker compose up -d --build`
4. In Pangolin, add a resource pointing at `http://bilkatogo-mcp:8000`, **with Pangolin's own
   authentication turned off** (it is a browser flow that Claude can't complete; this server checks
   the API key itself).
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
| `BILKATOGO_STORE_ID` | `1666` | Algolia store id for stock/assortment filtering |
| `BILKATOGO_MAX_QUANTITY` | `20` | Largest quantity a single cart call may set |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxy addresses whose `X-Forwarded-*` headers are trusted |
| `RATE_LIMIT_PER_MIN` | `120` | Global request limit |
| `AUTH_FAIL_LIMIT_PER_MIN` | `10` | Failed-auth attempts per minute before everything is refused for a while |

At least one login source is needed the first time (token, or email + password). Order tried:
saved token, then `BILKATOGO_LOGIN_TOKEN`, then email/password. If all fail, the tools return an
error saying so.

### Log in once, then remove the credentials

    docker compose run --rm bilkatogo-mcp python server.py --check-login

Prints `OK: authenticated via …` or `FAILED: …` (never a secret) and saves the token to the data
volume. After that you can remove the email/password (or token) secrets from `compose.yaml` and
`secrets/`. If the saved token later expires and no credentials are configured, provide a fresh
token or credentials again. The password, if you configure one, sits in `secrets/`; use a
password you don't reuse elsewhere.

Tools: search_products, get_cart, set_cart_quantity, add_to_cart, clear_cart, list_orders,
get_favourites, get_delivery_date. No checkout.

Local run without Docker: `BILKATOGO_LOGIN_TOKEN=… MCP_API_KEY=… uv run --python 3.12 server.py`

## Security notes

- Product, cart and order text comes from Bilka and is untrusted; tool descriptions tell the model
  not to follow instructions found in it. `clear_cart` should only run after explicit confirmation.
- `list_orders` and `get_delivery_date` return trimmed data (no name, address, door or pickup codes).
- The Bilka session can do more than these tools: treat `secrets/`, the `bilkatogo-data` volume and
  its backups like a password. Use a password you don't reuse.
- Every container on the `newt` network can reach this server; prefer a network shared only with newt.
- The failed-auth limiter is global: repeated bad keys can lock you out for up to a minute.
- The image installs exactly what `uv.lock` pins (`uv sync --locked`), and both base images are
  pinned by digest. Dependabot opens weekly PRs for Python packages, Docker images and GitHub
  Actions; CI (`.github/workflows/ci.yml`) runs lint, tests and a container smoke test on each.

## Development

    uv sync                 # installs runtime + dev dependencies
    uv run ruff check .
    uv run pytest
