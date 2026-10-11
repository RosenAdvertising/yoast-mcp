<p align="center"><a href="https://rosenadvertising.com/datalink/?utm_source=github&utm_medium=readme-banner&utm_campaign=yoast-mcp"><img src="https://image.rosenadvertising.com/datalink/readme-banner-v2.png" alt="DataLink by Rosen Advertising: don't want to install and run this yourself? Get it hosted." width="100%"></a></p>

# Yoast SEO MCP server

[![CI](https://github.com/RosenAdvertising/yoast-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/RosenAdvertising/yoast-mcp/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP 2026-07-28](https://img.shields.io/badge/MCP-2026--07--28-7C3AED.svg)](https://modelcontextprotocol.io)

Give Claude and other MCP clients read-only access to Yoast SEO metadata and scores on a WordPress site.

Yoast SEO MCP server is a [Model Context Protocol](https://modelcontextprotocol.io) server for [Yoast SEO](https://yoast.com/), the WordPress SEO plugin. It registers 10 tools, all read-only. It runs over stdio by default, for desktop clients such as Claude Desktop, and offers an opt-in stateless Streamable HTTP mode that implements MCP specification 2026-07-28. WordPress credentials stay on the machine that runs the server: they come from environment variables, never from tool arguments or requests. The server connects to the site's WordPress REST API and Yoast endpoints and does not modify content or settings.

## Features

- Retrieve Yoast SEO metadata for a page URL, or for a post by ID or slug.
- Review SEO, readability and inclusive-language scores for recently modified posts.
- Retrieve Schema Aggregator output for a post type, and the map of enabled Schema Aggregator endpoints.
- Retrieve SEO metadata for a custom post type archive.
- List the Yoast abilities a site exposes, with their input and output schemas.

## Tools

The server registers 10 tools:

| Tool | What it does |
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

- Python 3.11+
- A WordPress site using HTTPS
- A WordPress account with an Application Password
- Yoast SEO endpoints enabled on the site; score tools additionally require WordPress 6.9+ and the relevant Yoast abilities
- An MCP client such as Claude Desktop

## Installation

Install [uv](https://docs.astral.sh/uv/), then clone the repository and install its locked dependencies:

```bash
git clone https://github.com/RosenAdvertising/yoast-mcp.git
cd yoast-mcp
uv sync --locked
```

## Configuration

Set these environment variables in the MCP client's environment. `.env.example` lists them.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `WORDPRESS_SITE_URL` | Yes | none | HTTPS site origin only, such as `https://www.example.com`; do not include a path or `/wp-json`. |
| `WORDPRESS_USERNAME` | Yes | none | WordPress username for the dedicated integration account. |
| `WORDPRESS_APPLICATION_PASSWORD` | Yes | none | Application Password generated for that account. |
| `YOAST_HTTP_TIMEOUT_SECONDS` | No | `20` | Request timeout in seconds; must be greater than zero. |
| `YOAST_MAX_RETRIES` | No | `3` | Retries for HTTP 429 and 5xx responses; zero or greater. |
| `YOAST_RETRY_BACKOFF_SECONDS` | No | `0.5` | Base retry delay in seconds; zero or greater. |

Use a dedicated WordPress user with the minimum capabilities needed by the endpoints. The server sends HTTP Basic Authentication over HTTPS. It reads configuration from the process environment and does not load dotenv files.

Initialization and tool listing work without credentials. Tool calls return a configuration error until the three required variables are set. Two commands help with local setup:

```bash
uv run yoast-mcp-setup
uv run yoast-mcp-verify
```

`yoast-mcp-setup` prints instructions for the environment variables: export them in the environment your MCP client uses, then restart the client. `yoast-mcp-verify` checks the local configuration and exits with code 2 if it is missing or invalid. It does not contact WordPress or prove authentication. Neither command saves or prints secret values.

## Usage with Claude Desktop

Add the server to Claude Desktop's configuration file (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "yoast-seo": {
      "command": "uv",
      "args": ["run", "--locked", "--directory", "/absolute/path/to/yoast-mcp", "yoast-mcp"],
      "env": {
        "WORDPRESS_SITE_URL": "https://www.example.com",
        "WORDPRESS_USERNAME": "wordpress-integration-user",
        "WORDPRESS_APPLICATION_PASSWORD": "replace-with-your-application-password"
      }
    }
  }
}
```

Replace `/absolute/path/to/yoast-mcp` with the path of your clone and the example values with your site's, then restart Claude Desktop. Keep real credentials in your client's protected environment or secret store. Any other stdio MCP client uses the same command and arguments.

## HTTP mode

Stdio is the default. Set `YOAST_MCP_TRANSPORT=streamable-http` to serve the stateless Streamable HTTP transport from MCP specification 2026-07-28 at `/mcp`. Each request stands alone: no initialization handshake and no `Mcp-Session-Id`. Clients on earlier protocol versions are served on the same endpoint.

> **Security: this endpoint has no authentication and no TLS.** Anyone who can reach the port can run every tool with this server's vendor credentials. Keep the default loopback bind (`127.0.0.1`), or put the server behind an authenticating TLS proxy on a private network. `YOAST_MCP_ALLOWED_HOSTS` and `YOAST_MCP_ALLOWED_ORIGINS` protect against browser DNS rebinding, not against direct callers. A proxy in front of it needs connection and idle timeouts: a legacy-style `GET /mcp` with `Accept: text/event-stream` holds a stream open until the client disconnects.

| Variable | Default | Purpose |
| --- | --- | --- |
| `YOAST_MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http`. An empty value selects `stdio`; any other value exits. |
| `YOAST_MCP_HOST` | `127.0.0.1` | Bind address. `127.0.0.1`, `localhost` and `::1` use the SDK's built-in Host and Origin checks; any other value requires `YOAST_MCP_ALLOWED_HOSTS`. |
| `PORT` | `8080` | Port; must be an integer. |
| `YOAST_MCP_ALLOWED_HOSTS` | unset | Comma-separated `Host` header values accepted on a non-loopback bind, such as `mcp.example.com:8080` or `mcp.example.com:*`. The server exits if it is unset on a non-loopback bind. |
| `YOAST_MCP_ALLOWED_ORIGINS` | unset | Comma-separated `Origin` values accepted on a non-loopback bind, such as `https://client.example.com`. Requests without an `Origin` header are accepted. |

WordPress credentials come from the same configuration as stdio (see [Configuration](#configuration)), never from the request.

```bash
YOAST_MCP_TRANSPORT=streamable-http PORT=8080 uv run --locked yoast-mcp
```

Point the MCP client at `http://127.0.0.1:8080/mcp`.

## Error handling

A failed tool call returns an MCP error result (`isError`) with a fixed message. WordPress and Yoast error messages, codes and response bodies are never returned or logged.

- Missing or invalid configuration: a message that names `WORDPRESS_SITE_URL`, `WORDPRESS_USERNAME`, `WORDPRESS_APPLICATION_PASSWORD` and `yoast-mcp-setup`. This includes an invalid timeout, retry or backoff value, which is reported when a tool is called, not at startup.
- HTTP 401, 403, 404 and 429: a short message that says what to check (credentials, account permissions, the record ID, or waiting before a retry). WordPress permission failures arrive as 401 or 403 and get the authentication or access-denied message.
- HTTP 5xx: a "Service unavailable" message.
- Any other HTTP status, a response that is not the expected JSON, or a connection failure or timeout: "Request rejected or response invalid. Check inputs and API configuration."
- Checks made inside a tool, such as an invalid post type name, a page URL outside the configured site, or an endpoint that returns JSON that is not an array, return their own message that names the problem.

HTTP 429 and 5xx responses are retried up to `YOAST_MAX_RETRIES` times (default 3). The delay starts at `YOAST_RETRY_BACKOFF_SECONDS` and doubles on each retry. A `Retry-After` header, in seconds or as an HTTP date, sets the delay instead. Connection failures and timeouts are not retried. The request timeout is `YOAST_HTTP_TIMEOUT_SECONDS` (default 20).

The server exits with status 1 and a message that names the setting when `YOAST_MCP_TRANSPORT` is unsupported, `PORT` is not an integer, or `YOAST_MCP_HOST` is not a loopback address and `YOAST_MCP_ALLOWED_HOSTS` is unset.

## Behavior and limits

- WordPress collection requests use bounded pagination, with at most 100 records per page and a caller-controlled result limit.
- Schema Aggregator page sizes are controlled by Yoast and can vary by post type. The tool accepts the documented page number and returns the response as parsed JSON when possible, otherwise as raw text with its content type.
- Yoast's classic REST feature and Schema Aggregator must be enabled for their respective tools. Schema Aggregator may be disabled in site settings.

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

## Testing

The test suite runs offline and needs no WordPress site: every WordPress and Yoast request is intercepted at the HTTP layer with `respx`. It covers each tool's requests and responses, input validation, page URL scope checks, pagination and retries, error handling that withholds vendor text, configuration loading, and the Streamable HTTP transport including the 2026-07-28 wire format, Host and Origin checks and stateless requests.

```bash
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
```

CI runs the suite on every push and pull request to `main`.

## License

MIT. See [LICENSE](LICENSE).
