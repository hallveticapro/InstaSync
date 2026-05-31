# InstaSync

InstaSync is a small self-hosted API for downloading the highest-quality
available public Instagram profile picture. It is designed to replace the
unavailable API used by an Apple Shortcut and to run as a Docker container on
Unraid.

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

InstaSync resolves each uncached profile through Instaloader first and uses
Instaloader's highest-quality `Profile.profile_pic_url` exactly as returned. If
Instaloader cannot resolve the profile, InstaSync falls back to Instagram's
undocumented `web_profile_info` endpoint. The compatibility fallback prefers
`profile_pic_url_hd` and uses `profile_pic_url` only when the HD field is absent.
It identifies itself with an Android mobile user agent to avoid frontend
redirect behavior. When a session file is configured, both adapters use its
cookies. Signed CDN URLs are never rewritten.

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
| `INSTAGRAM_APP_ID` | `936619743392459` | Public Instagram web app ID sent by the compatibility fallback. |
| `INSTAGRAM_USERNAME` | unset | Optional Instagram account whose Instaloader session should be loaded. |
| `INSTALOADER_SESSION_FILE` | unset | Optional mounted Instaloader session file, such as `/data/session-hallveticapro`. |
| `REQUEST_TIMEOUT_SECONDS` | `15` | Timeout for Instaloader, fallback metadata, and image requests. |
| `MAX_IMAGE_BYTES` | `10485760` | Maximum accepted profile-picture size. |

Set `INSTAGRAM_USERNAME` and `INSTALOADER_SESSION_FILE` together or leave both
unset. The session file contains reusable cookies, not your Instagram password.

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

Create the persistent host directory from the Unraid terminal:

```bash
mkdir -p /mnt/user/appdata/instasync
chown -R 99:100 /mnt/user/appdata/instasync
```

In the Unraid WebGUI, open **Docker** and add or edit the container with these
settings:

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

The `/data` mapping is required. It stores the image cache and the optional
Instaloader session file outside the container so both survive image updates and
container recreation. The repository also includes an
[Unraid template](unraid/instasync.xml) with this mapping preconfigured.

Apply the container configuration, then verify the live bind mount from the
Unraid terminal:

```bash
docker inspect InstaSync \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

The output must include:

```text
/mnt/user/appdata/instasync -> /data
```

Enable auto-start after confirming the health check passes. If the container
logs show cache-directory permission errors, ensure the appdata directory is
writable by Unraid's standard container account, UID `99` and GID `100`.

Test the local deployment:

```bash
curl http://<unraid-ip>:9000/healthz
curl -o profile.jpg http://<unraid-ip>:9000/insta/instagram
```

### Configure An Instaloader Session

Anonymous Instagram requests can be rate-limited aggressively. If the container
logs show Instagram `429` responses, first verify the `/data` bind mount as
described above. Leave `INSTAGRAM_USERNAME` and `INSTALOADER_SESSION_FILE` unset
until the session file exists, then create a logged-in Instaloader session once:

```bash
docker exec -it InstaSync \
  instaloader \
  --login=hallveticapro \
  --sessionfile=/data/session-hallveticapro
```

Enter the password and two-factor code interactively if prompted. Instaloader
stores session cookies in `/mnt/user/appdata/instasync/session-hallveticapro`
through the existing `/data` volume mapping.

The image includes a compatibility patch for
[Instaloader issue #2487](https://github.com/instaloader/instaloader/issues/2487).
Unpatched Instaloader versions can save an empty `sessionid` cookie after login,
causing persistent `401 Unauthorized` responses. If your session file was
created by an older InstaSync image, remove it and recreate it after updating
the container:

```bash
rm -f /mnt/user/appdata/instasync/session-hallveticapro
```

You can verify that the recreated file contains a usable session ID without
printing the secret:

```bash
docker exec InstaSync python -c \
  "import pickle; data=pickle.load(open('/data/session-hallveticapro','rb')); print('sessionid present:', bool(data.get('sessionid')))"
```

If Instagram still rejects Instaloader's interactive login, create the session
from browser cookies instead. Log in to Instagram in a browser, open its
developer tools, and copy the Instagram-domain cookie values. Then run:

```bash
docker exec -it InstaSync python scripts/import_instagram_session.py \
  --output=/data/session-hallveticapro
```

Paste the required `sessionid` when prompted. The helper also accepts optional
`csrftoken`, `ds_user_id`, `mid`, and `ig_did` values. Prompts are hidden, the
cookies are stored with private file permissions, and secrets are not placed in
your shell history.

For a headless import, inject cookie values through environment variables:

```bash
docker exec \
  --env INSTAGRAM_SESSIONID \
  --env INSTAGRAM_CSRFTOKEN \
  InstaSync \
  python scripts/import_instagram_session.py \
  --from-env \
  --output=/data/session-hallveticapro
```

The optional environment variables are `INSTAGRAM_DS_USER_ID`, `INSTAGRAM_MID`,
and `INSTAGRAM_IG_DID`. You can also mount a JSON secret file containing the
cookie names and values, then run:

```bash
docker exec InstaSync python scripts/import_instagram_session.py \
  --cookies-json-file=/data/instagram-cookies.json \
  --output=/data/session-hallveticapro
```

Do not add a profile target to this one-time login command. For example,
`instaloader instagram` is an anonymous profile download, not a session setup
check, and Instagram may reject its GraphQL request with `403 Forbidden`.

To test a profile download with the persisted authenticated session, always pass
the same `/data` session path explicitly:

```bash
docker exec -it InstaSync \
  instaloader \
  --login=hallveticapro \
  --sessionfile=/data/session-hallveticapro \
  instagram
```

Confirm that the file exists on the Unraid host before editing or recreating the
container:

```bash
ls -l /mnt/user/appdata/instasync/session-hallveticapro
```

The loaded cookies authenticate the primary Instaloader lookup and the
`web_profile_info` compatibility fallback.

Then edit the Unraid container and add:

| Variable | Value |
| --- | --- |
| `INSTAGRAM_USERNAME` | `hallveticapro` |
| `INSTALOADER_SESSION_FILE` | `/data/session-hallveticapro` |

Apply the container update and check the logs for:

```text
Loaded Instaloader session for hallveticapro
```

You can also verify the loaded state without relying on log history:

```bash
curl http://<unraid-ip>:9000/healthz
```

The response should include:

```json
{"status":"ok","instaloader_session":"loaded"}
```

Do not publish or share the session file. If Instagram expires the session,
repeat the one-time `docker exec` command.

If a session file was previously created before `/data` was mapped to
`/mnt/user/appdata/instasync`, recreate it after adding the mapping. Files stored
only inside an old container or anonymous Docker volume are not copied into the
new host directory automatically.

### Docker Compose Alternative

The included [`compose.yaml`](compose.yaml) encodes the same required bind mount:

```yaml
volumes:
  - /mnt/user/appdata/instasync:/data
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

Instagram may change Instaloader-facing behavior without notice, and the
`web_profile_info` compatibility fallback is undocumented. The persistent cache
and stale-image fallback reduce disruption, but a future Instagram change may
require an adapter update.

The container temporarily installs the immutable Instaloader patch from
[PR #2696](https://github.com/instaloader/instaloader/pull/2696) to match
Instagram's current profile-metadata GraphQL document ID and flags. The patch is
pinned to commit
[`4a7ac19d`](https://github.com/npiriou/instaloader/commit/4a7ac19d8ae1ab19e3ef896f2d32a08c2b107613)
so image builds remain reproducible while the upstream pull request is open.

If both upstream adapters are rate-limited and no cached picture exists, the API
returns `503 Service Unavailable` with a `Retry-After` header. A stale cached
picture remains available during temporary upstream failures. During an
Instagram `Retry-After` window, the service serves cached images and rejects
uncached requests immediately instead of repeatedly querying Instagram.

## Attribution

This is a fresh, focused implementation. Its Shortcut-compatible endpoint was
inspired by the behavior of
[AlexisTonneau/currency-converter](https://github.com/AlexisTonneau/currency-converter).
No source code was copied from that repository because it does not include a
redistribution license.
