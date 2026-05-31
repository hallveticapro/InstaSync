# InstaSync

InstaSync is a small self-hosted API for downloading the highest-quality public
Instagram profile picture exposed by Instagram's web profile metadata endpoint.
It is designed to replace the unavailable API used by an Apple Shortcut and to
run as a Docker container on Unraid.

## API

Download a public profile picture:

```text
GET /insta/{username}
```

Example:

```bash
curl -o profile.jpg https://instasync.example.com/insta/instagram
```

The service normalizes usernames to lowercase and accepts Instagram-style
usernames containing letters, numbers, underscores, and non-consecutive periods.
Private profiles are not supported.

InstaSync requests Instagram's undocumented `web_profile_info` endpoint and uses
`profile_pic_url_hd` exactly as returned. If Instagram omits that field, the
service falls back to `profile_pic_url`. Signed CDN URLs are never rewritten.

Responses include an `X-Cache` header:

| Value | Meaning |
| --- | --- |
| `MISS` | The image was downloaded from Instagram and cached. |
| `HIT` | A fresh cached image was returned. |
| `STALE` | Instagram refresh failed, so an older cached image was returned. |

Container health is available at:

```text
GET /healthz
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CACHE_DIR` | `/data/cache` | Persistent image-cache directory. |
| `CACHE_TTL_SECONDS` | `86400` | Cache freshness window in seconds. |
| `INSTAGRAM_APP_ID` | `936619743392459` | Public Instagram web app ID sent with metadata requests. |
| `REQUEST_TIMEOUT_SECONDS` | `15` | Timeout for metadata and image requests. |
| `MAX_IMAGE_BYTES` | `10485760` | Maximum accepted profile-picture size. |

## Publish To GHCR

This repository includes a GitHub Actions workflow that tests the application,
builds `linux/amd64` and `linux/arm64` images, and publishes them to:

```text
ghcr.io/<github-user>/<repository>:latest
```

Pushes to `main` publish `latest` and `sha-<commit>` tags. Tags such as `v1.0.0`
also publish the matching version tag.

The first GHCR package is private by default. After the first successful
workflow run:

1. Open your GitHub profile or organization.
2. Open **Packages**, then select the container package.
3. Open **Package settings**.
4. Under **Danger Zone**, change the package visibility to **Public**.

## Deploy On Unraid

In the Unraid WebGUI, open **Docker** and add a container with these settings:

| Setting | Value |
| --- | --- |
| Name | `InstaSync` |
| Repository | `ghcr.io/<github-user>/<repository>:latest` |
| Network Type | `Bridge` |
| Container Port | `9000` |
| Host Port | `9000` |
| Container Path | `/data` |
| Host Path | `/mnt/user/appdata/instasync` |
| Access Mode | `Read/Write` |

Enable auto-start after confirming the health check passes. If the container
logs show cache-directory permission errors, ensure the appdata directory is
writable by Unraid's standard container account, UID `99` and GID `100`.

Test the local deployment:

```bash
curl http://<unraid-ip>:9000/healthz
curl -o profile.jpg http://<unraid-ip>:9000/insta/instagram
```

## Expose With Nginx Proxy Manager

This setup assumes Nginx Proxy Manager is already running and your DNS record
points to your home connection.

1. In Nginx Proxy Manager, create a **Proxy Host** for your chosen domain.
2. Set the scheme to `http`, the forward hostname or IP to your Unraid server,
   and the forward port to `9000`.
3. On the **SSL** tab, request a Let's Encrypt certificate.
4. Enable **Force SSL** and save the proxy host.
5. Update the Shortcut endpoint to:

   ```text
   https://instasync.example.com/insta/{username}
   ```

> [!WARNING]
> This selected deployment uses HTTPS but no authentication. Anyone who finds
> the URL can call the endpoint, consume server bandwidth, and increase the
> chance of Instagram rate-limiting your home IP. Add an Nginx Proxy Manager
> Access List or another authentication layer if that tradeoff stops being
> acceptable.

## Development

Install the dependencies and run the tests:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Run the service locally:

```bash
mkdir -p .data/cache
CACHE_DIR=.data/cache uvicorn app.main:app --host 0.0.0.0 --port 9000
```

Instagram's `web_profile_info` endpoint is undocumented and may change without
notice. The persistent cache and stale-image fallback reduce disruption, but a
future Instagram change may require an adapter update.

## Attribution

This is a fresh, focused implementation. Its Shortcut-compatible endpoint was
inspired by the behavior of
[AlexisTonneau/currency-converter](https://github.com/AlexisTonneau/currency-converter).
No source code was copied from that repository because it does not include a
redistribution license.

