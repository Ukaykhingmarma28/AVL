# Hosting the listener on Dokploy, with a domain

Best fit of the three options: you control both the hostname **and** the port.
Railway assigns the port and will not let you change it.

## The distinction that matters

Two different things are both called "domain":

| | What it is | Works for the listener? |
|---|---|---|
| Dokploy **Domain** button | Traefik HTTP route | **No.** HTTP only |
| Cloudflare **A record** | DNS name → IP | **Yes** |

A DNS A record is protocol-agnostic. It maps a name to an IP and stops there.
The tracker resolves `gps.ukaykhing.com` to your server IP, then opens a raw
TCP connection to port 5027 on that IP. Traefik is never involved.

That is why the earlier `timescale.ukaykhing.com` attempt failed: it was a
*proxied* Cloudflare record feeding Traefik, so it could only ever carry HTTP.

## Setup

### 1. DNS — grey cloud, not orange

In Cloudflare, add:

```
Type: A     Name: gps     Content: <your VPS IP>     Proxy: DNS only
```

**Proxy status must be DNS only (grey cloud).** An orange-cloud record routes
through Cloudflare's HTTP proxy, which cannot carry the Teltonika protocol.
Confirm with `dig +short gps.ukaykhing.com` — it must return *your* server IP,
not a `104.21.x` / `172.67.x` Cloudflare address.

### 2. Dokploy — publish the port, add no domain

Create the application from this repo (it builds from `Dockerfile`).

- Under **Ports** / port mappings, publish **`5027` → `5027`**
- Leave the **Domains** section **empty**

Adding a domain there attaches a Traefik HTTP router and produces exactly the
502 seen earlier.

Alternatively, deploy `docker-compose.yml` as a Dokploy Compose application —
it already publishes 5027 and keeps the database on `127.0.0.1`.

### 3. Firewall

```bash
sudo ufw allow 5027/tcp
```

Cloud-provider firewalls (DigitalOcean, Hetzner) are separate and need the
same rule.

### 4. Point the devices at the name

Parameter 2004 accepts a hostname:

```
setparam 2004:gps.ukaykhing.com
setparam 2005:5027
```

Verify the parameter ids against your firmware version first; they have moved
between releases.

### 5. Verify before touching real vehicles

```bash
dig +short gps.ukaykhing.com          # must be your VPS IP
nc -zv gps.ukaykhing.com 5027         # must connect
python3 mock_device.py --host gps.ukaykhing.com --port 5027 --count 5
```

## Why this beats the alternatives here

**Port 5027 is yours.** Railway assigns a random proxy port that cannot be
changed, and recreating the proxy reassigns it — meaning an SMS to every
tracker in the fleet. Here the port is fixed by you.

**The hostname is yours.** If the server moves, edit one A record. The fleet
never gets reconfigured.

**The database stays private.** `docker-compose.yml` binds Postgres to
`127.0.0.1`, so the listener reaches it over loopback and it is never exposed.
That removes the unencrypted-public-link problem entirely: the Railway TCP
proxy offers no SSL, so fleet positions would otherwise cross the internet in
cleartext.

## Keep in mind

Cloudflare gives you no DDoS protection on this record, since the traffic
bypasses their proxy. Port 5027 is directly exposed, so turn on the IMEI
allowlist before real data flows:

```
--allowlist /opt/teltonika/allowed_imeis.txt
```

Without it, anyone who finds the port can inject positions for any IMEI.

## Prerequisite: a real public IP

This whole approach needs the VPS to have a routable public IP. It does not
work behind a tunnel.

Cloudflare Tunnel carries arbitrary TCP only if `cloudflared` is installed on
the **connecting client**. An FMB920 runs fixed firmware and cannot run it.
Spectrum is the clientless Layer 4 alternative, but custom TCP protocols there
require an Enterprise plan. Tailscale has the same shape: the client needs the
software.

The trackers open a plain TCP socket and nothing else. Any hop that expects
HTTP (Traefik, the Cloudflare HTTP proxy) or client software (a tunnel) breaks
the path.

Without a public IP, host the listener on Railway instead — its TCP proxy
gives a public `host:port` any TCP client can reach. See `deploy-railway.md`.
