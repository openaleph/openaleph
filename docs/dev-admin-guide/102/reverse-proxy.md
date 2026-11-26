# Reverse proxy

The OpenAleph API doesn't enforce HTTPS, set security headers, handle CORS or rate limit requests. A production deployment needs a public-facing reverse proxy (nginx, Traefik, Caddy, a Kubernetes ingress, …) that does.

The nginx inside the `aleph-ui` image only serves the UI build and passes `/api` through to the API service. It sets none of the settings below and isn't meant to face the internet. Point the reverse proxy at it, or route `/api` directly to the API service (port `8000`) and everything else to the UI (port `8080`).

## Required

### TLS

Terminate TLS, redirect HTTP to HTTPS and send `Strict-Transport-Security`. Set `ALEPH_UI_URL` to the public `https://` URL so the API generates `https` links (see [`ALEPH_FORCE_HTTPS`](configuration.md#aleph_force_https)).

### Security headers

Send these on all responses, including errors (nginx: `always`):

| Header | Value |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `SAMEORIGIN` |
| `Referrer-Policy` | `same-origin` |
| `Permissions-Policy` | `accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()` |
| `Content-Security-Policy` | `default-src 'self' 'unsafe-inline' 'unsafe-eval' data: *` |

### Rate limiting

The API doesn't rate limit anonymous requests. If password login is enabled, limit at least these unauthenticated endpoints per client IP:

- `POST /api/2/sessions/login` – password brute force
- `POST /api/2/roles/code` – sends a sign-up e-mail to any address

Both are disabled when `ALEPH_PASSWORD_LOGIN` is off, which is the default once OAuth (e.g. Keycloak) is configured.

Public instances should also limit anonymous `/api` traffic. A request is authenticated if it carries an `Authorization` header or an `api_key` query parameter.

### Uploads, timeouts and streaming

- **Body size**: document uploads (`/api/2/collections/<id>/ingest`) can be large, so raise the request body limit.
- **Timeouts**: exports and the entity stream endpoints (`/api/2/entities/_stream`, `/api/2/collections/<id>/_stream`) can run for a long time. The API worker timeout is 3600 s.
- **Buffering**: disable request buffering for uploads. Streamed responses carry `X-Accel-Buffering: no`. Proxies that ignore this header need response buffering turned off for `/api`.

### Client IP

Every proxy in front of the API must append the client address to `X-Forwarded-For` (nginx: `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`, as the UI image does). Set [`ALEPH_TRUSTED_PROXIES`](configuration.md#aleph_trusted_proxies) to the number of proxies between the client and the API:

- `2` (reverse proxy → UI nginx → API)
- `1` (reverse proxy routes `/api` directly to the API, or the UI image is exposed directly)

If the value is too low, the logs show a proxy's IP. If it's too high, clients can set their own logged IP via the header.

## Optional

### CORS

The UI calls the API from the same origin and needs no CORS. Add CORS headers for `/api` only if browser apps on other origins use the API, e.g. custom front ends. Echo allowed origins in `Access-Control-Allow-Origin` (`*` doesn't work together with `Access-Control-Allow-Credentials: true`), allow the `Authorization` and `Content-Type` headers, and answer `OPTIONS` preflights at the proxy.

### HTTP caching

The API sets `Cache-Control`, `ETag` and `Vary: Authorization, Accept-Language`. A shared cache (e.g. Varnish) must honour them: don't store `private` or non-`200` responses, and vary on `Authorization`.

## Example: nginx

```nginx
limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/m;

# Anonymous requests only: an empty key is not limited.
map "$http_authorization$arg_api_key" $anon_key {
    ""      $binary_remote_addr;
    default "";
}
limit_req_zone $anon_key zone=anon:10m rate=30r/m;

server {
    listen 80;
    server_name aleph.example.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name aleph.example.org;
    ssl_certificate     /etc/ssl/aleph.example.org.crt;
    ssl_certificate_key /etc/ssl/aleph.example.org.key;

    client_max_body_size    2000g;
    proxy_read_timeout      3600s;
    proxy_send_timeout      3600s;
    proxy_request_buffering off;

    proxy_set_header Host            $host;
    proxy_set_header X-Real-IP       $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options    "nosniff" always;
    add_header X-Frame-Options           "SAMEORIGIN" always;
    add_header Referrer-Policy           "same-origin" always;
    add_header Permissions-Policy        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()" always;
    add_header Content-Security-Policy   "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: *" always;

    location ~ ^/api/2/(sessions/login|roles/code)$ {
        limit_req zone=auth burst=10 nodelay;
        proxy_pass http://ui:8080;
    }

    location /api {
        limit_req zone=anon burst=100 nodelay;
        proxy_pass http://ui:8080;
    }

    location / {
        proxy_pass http://ui:8080;
    }
}
```
