# The licence signing service

LumaBLE checks Pro with a **signed receipt**: a short statement that a server
looked up a licence, found it good for one installation, and will vouch for it
until a stated time. The application holds only the public half of the signing
key, so it can check a receipt and cannot make one. That is the whole reason
the service exists — an application whose source anybody can read cannot keep a
secret, and a check that depended on one would not be a check.

The service is a single Cloudflare Worker. It stores nothing: no database, no
accounts, no customer data. It is asked a question, it asks Lemon Squeezy, and
it signs the answer.

```
LumaBLE ──▶ Worker ──▶ Lemon Squeezy
              │
              └──▶ signed receipt
```

## Address

```
https://lumable-license.lumable.workers.dev/v1/issue
```

Versioned from the first day. A contract that has to change later without
breaking installed builds needs somewhere to change *to*, and adding the
version afterwards means the unversioned path has to be kept working forever.

HTTPS only, and the client goes to that exact address. It does not follow
redirects: a redirect is how a licence key ends up being posted somewhere else.

The service refuses plain HTTP with `400 https_required`, before asking Lemon
Squeezy anything. workers.dev answers HTTP directly rather than redirecting to
HTTPS, so without this the address would work unencrypted, and a licence key in
an unencrypted request is a licence key on the wire.

## The request

`POST /v1/issue`, `Content-Type: application/json`

| Field | What it is |
|---|---|
| `license_key` | the key the person bought |
| `instance_id` | the activation, as Lemon Squeezy issued it |
| `installation_hash` | 43 characters, base64url of SHA-256 over the installation id |

### Checked before anything else

The request is judged on its own before Lemon Squeezy is asked anything. An
upstream call is the expensive part and the part with a rate limit on it, and
spending one on a request that was never going to work is how a service becomes
somebody else's denial of service.

- HTTPS only.
- `POST` only — anything else is `405`.
- `Content-Type: application/json`, with or without a charset after it.
- A `User-Agent` naming the application. Not the service's rule but
  Cloudflare's: the default `Python-urllib` signature is refused in front of
  the Worker with a `403` and an error page, so a client that does not say who
  it is never reaches the service at all. The client sends `LumaBLE/<version>`.
- At most 4 KiB of body — a larger one is `413`, refused without being read.
- `installation_hash` matches `^[A-Za-z0-9_-]{43}$` exactly. Not "starts with",
  not "at least": the hash has one shape, and anything else is a mistake or an
  attempt.
- `license_key` and `instance_id` are non-empty and no longer than 200
  characters.

A request that fails any of these is `400 malformed_request` — never
`403 invalid`. The two mean different things to the client: one is a bug on
this side, the other is a statement about somebody's licence, and only the
second may take Pro away.

## What the Worker does

1. Validates `license_key` + `instance_id` with Lemon Squeezy.

   A statement about a licence arrives with a 4xx as readily as a 200 — an
   unknown key comes back **404**, not the 400 this page first claimed. A 5xx
   is different and stays an outage whatever the body says: a service in
   trouble can return something that reads like an answer, and believing it
   would end a licence on the strength of an error page.
2. Requires `valid` to be true.
3. Requires `meta.variant_id` to equal `1776109`.
4. Requires `instance.id` to equal the `instance_id` that was asked about.
   Without this the answer could be about a different activation than the
   request named — the name would still match, because it is the name of
   whatever instance Lemon Squeezy chose to describe.
5. **Rebuilds the expected instance name** as `LumaBLE:<installation_hash>`
   from the hash it was given, and requires `instance.name` to equal it
   exactly. No prefix matching, no normalisation, no trimming.
6. Signs a receipt and returns it.

Step 5 is the binding, and the reason the request cannot be used to sign for
somebody else. Without it a valid key and instance would be enough to obtain a
receipt for *any* installation hash — one activation spread across as many
machines as anybody cared to type in. It needs no database: the name was fixed
when the instance was activated, and Lemon Squeezy gives it back.

Confirmed against the live API: a 51-character name is accepted, stored and
returned byte for byte, with no truncation and no normalisation.

## The receipt

```json
{
  "receipt_version": 1,
  "key_id": "k1",
  "audience": "lumable-pro",
  "license_id": "42",
  "instance_id": "inst-uuid-001",
  "variant_id": "1776109",
  "installation_hash": "6gMgc3K5w-RS6E8LZVKT6_HcWsMEA7UepSyCrmhaT4k",
  "issued_at": "2026-08-26T12:00:00+00:00",
  "expires_at": "2026-09-09T12:00:00+00:00",
  "signature": "<base64 Ed25519 over the canonical bytes>"
}
```

`expires_at` is fourteen days after `issued_at`. The client refuses anything
longer: a signed year would mean the signer had been changed or misconfigured,
and honouring it would turn one mistake into a permanent one.

### The bytes that are signed

Not the JSON. JSON leaves key order and escaping to whoever serialises it, and
the two sides here are different languages. The signature covers these fields,
in this order, as `name=value` lines joined by a single `\n`, encoded UTF-8:

```
receipt_version
key_id
audience
license_id
instance_id
variant_id
installation_hash
issued_at
expires_at
```

A value may not contain `\n`. The Worker must refuse to sign one that does,
rather than escaping it: a field allowed to carry the separator could spell out
a second field inside itself, and two different receipts would sign the same
bytes.

`signature` is base64 (standard alphabet, padded) of the raw 64-byte Ed25519
signature.

The authoritative definition is `app/license_receipt.py`; this document
describes it, and the tests in `tests/test_license_worker_contract.py` check
that a receipt built the way this page says is one the application accepts.

## Failures

The client tells these apart because they call for different things: one turns
Pro off at once, the rest leave everything exactly as it was.

| Status | `error` | What the client does |
|---|---|---|
| 200 | — | verifies, then replaces the stored receipt |
| 400 | `malformed_request` | keeps everything; a fault on this side |
| 400 | `https_required` | keeps everything; the address was not HTTPS |
| 403 | `wrong_product` | keeps everything; the licence is for something else |
| 403 | `invalid` | Pro off now, receipt removed |
| 403 | `revoked` | Pro off now, receipt removed |
| 405 | `method_not_allowed` | keeps everything |
| 409 | `instance_mismatch` | keeps everything; this installation cannot be issued for |
| 413 | `request_too_large` | keeps everything |
| 429 | `rate_limited` | keeps everything, tries later |
| 502 | `upstream_unavailable` | keeps everything, tries later |
| 5xx / no answer | — | keeps everything, tries later |

Anything that is not one of these, or a body that will not parse, is treated as
unavailable.

`invalid` and `revoked` are the only answers that take Pro away, and only
because the server reached Lemon Squeezy and was told so. Everything else —
including a Lemon Squeezy that is itself down or rate-limiting, which becomes
`502` or `429` here — leaves the stored key, instance and receipt exactly as
they were. A service that cannot answer must never be able to end somebody's
licence.

### How long an outage is survivable

A receipt already held keeps working until it expires, and no longer. That is
somewhere between fourteen days and nothing at all, depending on when the
outage started: a receipt refreshed this morning has its full fourteen days
left, and one refreshed thirteen days ago has an hour. Refreshing daily is what
keeps the usual case near the top of that range, not a guarantee that two weeks
of downtime go unnoticed.

### How quickly a revocation lands

With the network working, at the next daily refresh — so within a day of the
refund. The fourteen days are the *other* case: they are how long a revocation
can be delayed when the machine is offline or the service cannot be reached,
because then there is nothing to learn it from.

## The key

The private key lives in a Cloudflare Secret and nowhere else — not in this
repository, not in the application, not in a build. Keep a copy somewhere safe:
losing it means existing receipts keep working until they expire and no new
ones can be issued, which is repaired by shipping a build carrying a new public
key.

`key_id` names which key signed, so a new one can be introduced by shipping a
build that knows both and then signing with the newer. A `key_id` the
application does not know is refused rather than trusted.

## What the Worker must never do

- Sign without checking the instance name. That check *is* the binding.
- Trust `installation_hash` as a name. It is an input; the name comes back from
  Lemon Squeezy.
- Log the licence key, the request body, or a full response.
- Issue a receipt longer than fourteen days.
- Call Lemon Squeezy before the request has been judged on its own.
- Answer `403 invalid` for anything other than what Lemon Squeezy said. It is
  the one answer that switches somebody's Pro off, and a service that reaches
  for it when confused ends licences by accident. A licence for the wrong
  variant answers `wrong_product` rather than `invalid` for the same reason:
  the likeliest way to reach that branch is a new plan added to the store
  without the constant being updated, and a misconfiguration should look like
  an outage rather than a mass revocation.
- Serve anything over plain HTTP.
