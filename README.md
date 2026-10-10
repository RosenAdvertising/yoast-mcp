# Yoast SEO MCP server

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/RosenAdvertising/yoast-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/RosenAdvertising/yoast-mcp/actions/workflows/ci.yml)

A read-only [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for auditing Yoast SEO data on a WordPress site. It connects to the site's WordPress REST API and Yoast endpoints; it does not modify content or settings.

## Tools

The server provides 10 tools:

| Tool | Description |
| --- | --- |
| `get_url_seo_metadata` | Retrieve Yoast metadata for an absolute URL. |
| `get_post_seo_by_id` | Retrieve one post and its Yoast metadata by ID. |
| `get_post_seo_by_slug` | Find posts by exact slug with bounded pagination. |
| `get_recent_seo_scores` | Read SEO scores and focus keyphrases for recently modified posts. |
| `get_recent_readability_scores` | Read readability scores for recently modified posts. |
| `get_recent_inclusive_language_scores` | Read inclusive-language scores for recently modified posts. |
| `get_post_type_schema` | Retrieve one path-paginated Schema Aggregator page. |
| `get_schema_map` | Retrieve the XML map of enabled Schema Aggregator endpoints. |
| `get_custom_post_archive_seo` | Retrieve SEO metadata for a custom post type archive. |
| `list_yoast_abilities` | List Yoast abilities and their input/output schemas. |

All tools are read-only. The three score tools use the WordPress Abilities API and require the corresponding ability to be enabled and permitted for the configured user. Other endpoints also depend on the site's WordPress and Yoast configuration.

## Requirements

- Python 3.12
- A WordPress site using HTTPS
- A WordPress account with an Application Password
- Yoast SEO endpoints enabled on the site; score tools additionally require WordPress 6.9+ and the relevant Yoast abilities
- An MCP-compatible client

## Install from source

Install [uv](https://docs.astral.sh/uv/), then clone this repository and sync its locked dependencies:

```sh
git clone https://github.com/RosenAdvertising/yoast-mcp.git
cd yoast-mcp
uv sync --locked
```

## Configure

Set these environment variables in the MCP client's environment:

| Variable | Required | Purpose |
| --- | --- | --- |
| `WORDPRESS_SITE_URL` | Yes | HTTPS site origin only, such as `https://www.example.com`; do not include a path or `/wp-json`. |
| `WORDPRESS_USERNAME` | Yes | WordPress username for the dedicated integration account. |
| `WORDPRESS_APPLICATION_PASSWORD` | Yes | Application Password generated for that account. |
| `YOAST_HTTP_TIMEOUT_SECONDS` | No | Request timeout in seconds; defaults to `20`. |
| `YOAST_MAX_RETRIES` | No | Retries for HTTP 429 and 5xx responses; defaults to `3`. |
| `YOAST_RETRY_BACKOFF_SECONDS` | No | Base retry delay in seconds; defaults to `0.5`. |

Use a dedicated WordPress user with the minimum capabilities needed by the endpoints. The server sends HTTP Basic Authentication over HTTPS. It reads configuration from the process environment and does not load dotenv files.

## MCP client configuration

For clients that launch a local process, configure the absolute path to the cloned repository. For example, an MCP client supporting `cwd` and `env` can use:

```json
{
  "mcpServers": {
    "yoast-seo": {
      "command": "uv",
      "args": ["run", "--locked", "--directory", "/path/to/yoast-mcp", "yoast-mcp"],
      "env": {
        "WORDPRESS_SITE_URL": "https://www.example.com",
        "WORDPRESS_USERNAME": "wordpress-integration-user",
        "WORDPRESS_APPLICATION_PASSWORD": "set-this-in-your-client's-secret-environment"
      }
    }
  }
}
```

Replace `/path/to/yoast-mcp` with the local clone path and provide the password through your MCP client's protected environment or secret store.

## HTTP mode

Stdio stays the default. Set `YOAST_MCP_TRANSPORT=streamable-http` to serve stateless Streamable HTTP (protocol 2026-07-28). The endpoint is `POST /mcp`. Credentials come from the same environment variables as stdio, never from the request.

> **Security: this endpoint has no authentication and no TLS.** Anyone who can reach the port can run every tool, including write and delete tools, with this server's vendor credentials. Keep the default loopback bind (`127.0.0.1`), or put the server behind an authenticating TLS proxy on a private network. `YOAST_MCP_ALLOWED_HOSTS` and `YOAST_MCP_ALLOWED_ORIGINS` protect against browser DNS rebinding, not against direct callers. A proxy in front of it needs connection and idle timeouts: a legacy-style `GET /mcp` with `Accept: text/event-stream` holds a stream open until the client disconnects.

| Variable | Required | Purpose |
| --- | --- | --- |
| `YOAST_MCP_TRANSPORT` | No | `stdio` (default) or `streamable-http`. |
| `YOAST_MCP_HOST` | No | Bind address. Defaults to `127.0.0.1`. |
| `PORT` | No | Bind port. Defaults to `8080`. Must be an integer. |
| `YOAST_MCP_ALLOWED_HOSTS` | When the host is not loopback | Comma-separated `Host` values allowed for DNS-rebinding protection. |
| `YOAST_MCP_ALLOWED_ORIGINS` | No | Comma-separated `Origin` values. Used only when the host is not loopback. |
| `WORDPRESS_SITE_URL` | Yes | HTTPS site origin only, such as `https://www.example.com`. |
| `WORDPRESS_USERNAME` | Yes | WordPress username for the dedicated integration account. |
| `WORDPRESS_APPLICATION_PASSWORD` | Yes | Application Password generated for that account. |
| `YOAST_HTTP_TIMEOUT_SECONDS` | No | Request timeout in seconds; defaults to `20`. |
| `YOAST_MAX_RETRIES` | No | Retries for HTTP 429 and 5xx responses; defaults to `3`. |
| `YOAST_RETRY_BACKOFF_SECONDS` | No | Base retry delay in seconds; defaults to `0.5`. |

Loopback binds (`127.0.0.1`, `localhost`, `::1`) rely on the SDK's own origin checks. Any other host requires `YOAST_MCP_ALLOWED_HOSTS`.

```sh
YOAST_MCP_TRANSPORT=streamable-http \
YOAST_MCP_HOST=127.0.0.1 \
PORT=8080 \
WORDPRESS_SITE_URL=https://www.example.com \
WORDPRESS_USERNAME=wordpress-integration-user \
WORDPRESS_APPLICATION_PASSWORD=set-this-in-the-environment \
uv run --locked --directory /path/to/yoast-mcp yoast-mcp
```

Clients send MCP requests to `http://127.0.0.1:8080/mcp`.

## Behavior and limits

- WordPress collection requests use bounded pagination, with at most 100 records per page and a caller-controlled result limit.
- HTTP 429 and 5xx responses receive bounded exponential retries and honor `Retry-After` when present.
- Schema Aggregator page sizes are controlled by Yoast and can vary by post type. The tool accepts the documented page number and returns the response as parsed JSON when possible, otherwise as raw text with its content type.
- WordPress REST errors, including permission failures, are returned with the API's message and code.
- Yoast's classic REST feature and Schema Aggregator must be enabled for their respective tools. Schema Aggregator may be disabled in site settings.

## Development

The tests use mocked HTTP responses and do not contact a live WordPress site.

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
```

## License

MIT. See [LICENSE](LICENSE).

## Local setup and verification

The server starts and answers MCP initialization and tool listing without credentials.
Tools report a configuration error until the required environment is provided.
Run `yoast-mcp-setup` for environment-variable instructions, then restart your MCP
launcher with those variables exported. Run `yoast-mcp-verify` to validate local
configuration (exit 2 if missing or invalid). This command does not contact the
vendor or prove authentication. Neither command saves or prints secret values.

## Page URL scope

`get_url_seo_metadata` sends `url` to the configured WordPress site's
`/wp-json/yoast/v1/get_head` metadata lookup. It identifies a page on that site:
its host must equal the `WORDPRESS_SITE_URL` host after case-insensitive IDNA
normalization and trailing-dot removal. Subdomains and unrelated public hosts
are refused. For example, `WORDPRESS_SITE_URL=https://law.example` permits
`https://LAW.EXAMPLE./practice/tax`, but not `https://other.example/practice/tax`.
There is no destination allowlist for this lookup. See
[Yoast's REST API documentation](https://developer.yoast.com/customization/apis/rest-api/)
for the site metadata endpoint and indexables behavior.

Page URLs must also be ASCII (use punycode for internationalized hosts), public
HTTPS without userinfo or fragments; private/local and alternate-numeric IP
forms remain rejected. The server contacts the configured WordPress API, not the
page URL. It does not resolve page hostnames locally; administrators remain
responsible for the configured site's DNS and network behavior.
