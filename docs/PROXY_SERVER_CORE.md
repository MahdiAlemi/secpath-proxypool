# Proxy server core

This document describes the local proxy-serving core after the server hardening phase. It is an engineering and operations reference, not deployment approval.

## Listener safety

The default listener address is `127.0.0.1`. An unauthenticated listener is permitted only on loopback.

A listener bound to any non-loopback address, including a private LAN address, must have listener authentication or the profile must explicitly set:

```json
{"allow_public_no_auth": true}
```

That override is intentionally explicit because it creates an open proxy for every host that can reach the bind address. Do not enable it on an Internet-facing interface.

HTTP, HTTPS, and SOCKS5 listeners use username/password authentication. SOCKS4 has no password authentication in the protocol; its optional listener check uses the SOCKS4 UserID field only. A SOCKS4 profile with a password is rejected instead of providing a false sense of password protection.

## Protected process configuration

Dashboard-started server processes receive only these profile references in their command line:

```text
--server-id <port>
--claim-token <short-lived-start-token>
--config-file <protected-runtime-json>
```

Listener usernames and passwords are not placed in process arguments. The runtime profile is stored under `.runtime/servers/` with mode `0600` and is removed when the profile is stopped or deleted. Persistent `.servers.json` is also written with mode `0600`.

Runtime files remain sensitive local data and are excluded from Git.

## Process lifecycle

Each server profile has a stable server ID, currently its listener port. Start uses an atomic reservation before the child process is launched. The child must claim that reservation with the matching token.

Runtime ownership is verified using all of the following:

- PID;
- process creation time;
- the exact `--server-id` process argument.

This prevents a recycled PID from being treated as a ProxyPool server. A duplicate Start returns a conflict instead of stopping or replacing the existing process. Stop sends `SIGTERM`, waits for graceful listener shutdown, and uses a bounded kill fallback only when required.

## Listener concurrency

The listener uses a bounded worker pool. `threads` controls active client workers and a bounded admission semaphore prevents an unbounded queue of accepted sockets. TLS handshakes are performed per accepted connection so one bad TLS client does not block the accept loop.

The listener handles `SIGTERM` and `SIGINT`, closes the accept socket, and waits for active handlers during graceful shutdown. Long-lived tunnels may exceed the dashboard grace period and then be terminated by the bounded fallback.

## Rotation behavior

Supported modes:

- `fixed`: selects one available upstream until it disappears from the candidate set;
- `per_connection`: selects a candidate for each client connection;
- `better_cost`: keeps the current candidate until a lower-cost candidate is available;
- `time`: rotates after `rotate_interval`;
- `sticky`: uses either an explicit upstream or deterministic client affinity.

An explicit sticky upstream may be configured as:

```text
id:123
http://proxy.example:3128
socks5://user@proxy.example:1080
proxy.example:3128
```

When `sticky_upstream` is blank, rendezvous hashing maps the client address to a stable candidate. Candidate order changes do not randomly remap all clients.

Failed connection attempts are excluded from the immediate retry. Cached candidates are revalidated against the current filtered candidate set.

## Candidate filters

Boolean filters are normalized to real booleans. In particular, the string `"false"` is no longer truthy. Protocol, status, capability, geographic, authentication, and cost filters are applied before selection.

Candidate data is periodically refreshed from the database. A fresh database schema is initialized before the server begins listening.

## Protocol behavior

### HTTP listener

The listener supports normal absolute-form HTTP proxy requests and `CONNECT` tunnels. It:

- enforces a bounded header size;
- validates request lines, destination host, and destination port;
- strips client `Proxy-Authorization` before forwarding;
- adds only the selected upstream proxy credentials;
- preserves streamed request bodies, including bytes pipelined after CONNECT headers;
- returns standard `400`, `407`, `502`, and `503` responses.

HTTPS destinations must use `CONNECT`.

### SOCKS4 listener

Only the CONNECT command is supported. SOCKS4a domain names are accepted. Frame fields are read exactly and zero-terminated fields have length limits.

### SOCKS5 listener

Only the CONNECT command is supported. IPv4, IPv6, and domain destinations are accepted. Authentication negotiation and username/password sub-negotiation follow the SOCKS5 framing rules. Unsupported methods and commands receive protocol-appropriate replies.

UDP ASSOCIATE and BIND are not implemented.

## Upstream connections

HTTP and HTTPS upstream proxies use CONNECT for tunnels. The CONNECT result must contain a real numeric 2xx status; a string that merely contains `200` is not accepted.

HTTPS upstream TLS is enabled based on the upstream protocol, not the port number. SNI and hostname verification refer to the upstream proxy host, never to the final destination. `insecure_upstream=true` disables certificate verification and should be used only for a deliberately trusted self-signed upstream.

SOCKS5 uses proxy-side DNS for domain destinations. SOCKS4 uses SOCKS4a where supported.

## Verification

Run:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard proxy_server tests
node --check dashboard/static/js/base.js
ruff check proxy_server dashboard/routes/server.py dashboard/utils/process.py tests/test_proxy_server_core.py
git diff --check
git status --short
```

The server core regression suite covers public-bind policy, boolean normalization, sticky selection, HTTPS proxy SNI, strict CONNECT status parsing, SOCKS5 method rejection, PID identity, protected process arguments, normal HTTP forwarding, and CONNECT tunnel byte forwarding.
