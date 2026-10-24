# bilkatogo-mcp

Unofficial, single-user MCP server for BilkaToGo (streamable HTTP, `/mcp`), protected by an API key.

- The Bilka account is fixed by config: a Gigya `login_token`.
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
5. Claude Code:

       claude mcp add --transport http bilkatogo https://bilka-mcp.example.com/mcp \
         --header "Authorization: Bearer $(cat secrets/mcp_api_key)"

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BILKATOGO_LOGIN_TOKEN` / `_FILE` | required | Gigya login_token of the Bilka account |
| `MCP_API_KEY` / `_FILE` | required | API key clients must send (min 24 chars) |
| `BILKATOGO_ALLOWED_HOSTS` | localhost only | Comma-separated Host headers to accept |
| `BILKATOGO_ALLOWED_ORIGINS` | localhost only | Comma-separated allowed Origins (browser clients) |
| `BILKATOGO_STORE_ID` | `1666` | Algolia store id for stock/assortment filtering |
| `RATE_LIMIT_PER_MIN` | `120` | Global request limit |
| `AUTH_FAIL_LIMIT_PER_MIN` | `10` | Failed-auth attempts per minute before everything is refused for a while |

When the login_token expires the tools fail with a message saying so; sign in again on
bilkatogo.dk, replace `secrets/bilkatogo_login_token` and `docker compose restart`.

Tools: search_products, get_cart, set_cart_quantity, add_to_cart, clear_cart, list_orders,
get_favourites, get_delivery_date. No checkout.

Local run without Docker: `BILKATOGO_LOGIN_TOKEN=… MCP_API_KEY=… uv run --python 3.12 server.py`
