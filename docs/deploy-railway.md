# Hosting the listener on Railway

Viable, with three configuration details that are easy to miss. The payoff is
that the listener and the database sit in the same Railway project, so record
traffic never leaves Railway's private network.

## 1. Create the service

New service → deploy from your repo. `railway.json` selects the Dockerfile
builder and sets the start command, so no further build config is needed.

## 2. Volume (required)

Railway's filesystem is **ephemeral** — anything outside a volume is lost on
every redeploy. `records.jsonl` is the durable system of record in this design
(see `docs/data-flow.md`), so losing it defeats the emit-before-ACK guarantee.

- Attach a volume, mount path **`/data`**
- Set **`RAILWAY_RUN_UID=0`**

The UID variable matters because the Dockerfile drops to the unprivileged
`teltonika` user, which does not own a freshly-created volume. Without it the
service crash-loops on a permission error at `/data/logs`. Railway's own
Timescale template sets the same variable for the same reason.

## 3. Database connection — use the private network

In the listener service's Variables, add a **reference**, not a literal:

```
DATABASE_URL = ${{timescaledb.DATABASE_URL}}
```

That resolves to `timescaledb.railway.internal:5432`. Both services are in the
same project, so the connection stays inside Railway.

This is strictly better than the public proxy: the TCP proxy link is
**unencrypted** (the server answers `N` to a Postgres SSLRequest), so routing
fleet positions over it would expose them in transit. The private network
avoids that entirely. Use `DATABASE_PUBLIC_URL` only from your laptop.

## 4. TCP proxy for the devices

Settings → Networking → **TCP Proxy** → port **`5027`**.

Railway returns something like `<your-proxy>.proxy.rlwy.net:23456`. Note the port —
it is assigned by Railway and is **not** 5027.

## 5. Point the devices at it

FMB920 parameter 2004 accepts a **domain name**, not only an IP, so the proxy
hostname works directly:

```
setparam 2004:<your-proxy>.proxy.rlwy.net
setparam 2005:23456
```

Confirm the parameter ids against your firmware version first; they have moved
between releases.

### Put a custom domain in front

Railway's TCP proxy accepts a custom domain: add a CNAME from
`gps.ukaykhing.com` to the proxy domain (without the port). Configure the
devices with **your** hostname instead of Railway's.

Do this before touching real vehicles. It is the difference between "re-point a
DNS record" and "send an SMS to every tracker in the fleet" if the backend ever
moves. The port still comes from Railway and cannot be changed, so the DNS
record protects you from a hostname change but not a port change.

## What to accept before committing

**The port is Railway's.** Deleting and recreating the TCP proxy assigns a new
one, and every device would need reconfiguring. Do not delete the proxy.

**Redeploys drop connections**, and a volume-attached service has a short
downtime window on every deploy. This is safe by design: unacknowledged
records stay in device memory and are retransmitted, and the insert is
idempotent on `(imei, ts, event_io_id)`. Expect a gap in ingest, not data loss.

**Threading caps throughput.** One thread per connection, comfortable to
roughly 500 devices. Beyond that, move to asyncio rather than scaling replicas
— replicas would split devices across instances arbitrarily.

## Railway versus a VPS

A VPS gives a static IP and port you control outright, which is why the repo
ships a systemd unit and a `docker-compose.yml`. Railway trades that control
for not administering a server, and the private-network database link is a
real security gain over a VPS talking to a hosted database.

The deciding constraint is the fleet: reconfiguring physical trackers is slow
and error-prone, so whichever you choose, put a custom domain in front of it.
