/**
 * The licence signing service.
 *
 * One endpoint. It is asked whether a licence key and activation are good for
 * a particular installation, it asks Lemon Squeezy, and it signs the answer.
 * It stores nothing: no database, no accounts, no customer data, no record of
 * who asked. The only thing it holds is the private half of a signing key,
 * which is what makes a receipt worth anything to an application whose source
 * anybody can read.
 *
 * The contract this implements is docs/license-worker.md, and the tests in
 * tests/test_license_worker_contract.py check that a receipt built the way it
 * describes is one the application accepts. Change one and all three move.
 */

const RECEIPT_VERSION = 1;
const KEY_ID = "k1";
const AUDIENCE = "lumable-pro";
const EXPECTED_VARIANT_ID = "1776109";
const INSTANCE_NAME_PREFIX = "LumaBLE:";
const LIFETIME_MS = 14 * 24 * 60 * 60 * 1000;

const MAX_BODY_BYTES = 4096;
const MAX_FIELD_LENGTH = 200;
const INSTALLATION_HASH = /^[A-Za-z0-9_-]{43}$/;

const LEMON_VALIDATE_URL = "https://api.lemonsqueezy.com/v1/licenses/validate";
const LEMON_TIMEOUT_MS = 8000;

// The order the signed fields are laid out in. Fixed, and the same tuple as
// SIGNED_FIELDS in app/license_receipt.py. Not JSON: JSON leaves key order and
// escaping to whoever serialises, and the two sides here are different
// languages that would not agree for long.
const SIGNED_FIELDS = [
  "receipt_version",
  "key_id",
  "audience",
  "license_id",
  "instance_id",
  "variant_id",
  "installation_hash",
  "issued_at",
  "expires_at",
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.protocol !== "https:") {
      // workers.dev answers plain HTTP directly rather than redirecting, and a
      // licence key in an unencrypted request is a licence key on the wire.
      // Nothing here can un-send one that has already arrived, but the service
      // must not be usable that way, and refusing before Lemon Squeezy is asked
      // means a key sent in the clear is at least not also validated.
      //
      // LumaBLE itself cannot reach this: its address is https and it refuses
      // redirects. This is for everything that is not LumaBLE.
      return fail(400, "https_required");
    }
    if (url.pathname !== "/v1/issue") {
      return fail(404, "not_found");
    }
    try {
      return await issue(request, env);
    } catch (_err) {
      // Deliberately without the error in it. Anything thrown here has been
      // near a licence key, and a stack trace is a place for one to end up.
      // Unavailable is also the honest answer: the client keeps everything it
      // has and tries again later, which is what a fault on this side should
      // cost somebody.
      return fail(502, "upstream_unavailable");
    }
  },
};

async function issue(request, env) {
  // ── the request, judged on its own ──────────────────────────────────
  // Before Lemon Squeezy is asked anything. The upstream call is the
  // expensive part and the part with a rate limit on it, and spending one on
  // a request that was never going to work is how a service becomes somebody
  // else's denial of service.
  if (request.method !== "POST") {
    return fail(405, "method_not_allowed", { Allow: "POST" });
  }

  const declared = Number(request.headers.get("content-length") || "0");
  if (declared > MAX_BODY_BYTES) {
    // Refused on the header alone, so an enormous body is never read.
    return fail(413, "request_too_large");
  }

  const contentType = (request.headers.get("content-type") || "").split(";")[0].trim();
  if (contentType.toLowerCase() !== "application/json") {
    return fail(400, "malformed_request");
  }

  const raw = await readCappedBody(request, MAX_BODY_BYTES);
  if (raw === null) {
    // A missing or untruthful Content-Length is not a way around the limit,
    // and the whole oversized body is never buffered in Worker memory.
    return fail(413, "request_too_large");
  }

  let body;
  try {
    body = JSON.parse(new TextDecoder().decode(raw));
  } catch (_err) {
    return fail(400, "malformed_request");
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return fail(400, "malformed_request");
  }

  const licenseKey = body.license_key;
  const instanceId = body.instance_id;
  const installationHash = body.installation_hash;

  if (!isField(licenseKey) || !isField(instanceId)) {
    return fail(400, "malformed_request");
  }
  if (typeof installationHash !== "string" || !INSTALLATION_HASH.test(installationHash)) {
    // One shape, and anything else is a mistake or an attempt. Not starts-with
    // and not at-least: a loose check here is a loose binding later.
    return fail(400, "malformed_request");
  }

  if (env.ISSUE_RATE_LIMITER) {
    const source = request.headers.get("cf-connecting-ip") || "unknown";
    const { success } = await env.ISSUE_RATE_LIMITER.limit({ key: source });
    if (!success) {
      return fail(429, "rate_limited");
    }
  }

  // 400 and never 403. The two mean different things to the client — one is a
  // bug on this side, the other is a statement about somebody licence — and
  // only the second may take Pro away.

  // ── what Lemon Squeezy says ─────────────────────────────────────────
  const answer = await validateWithLemon(licenseKey, instanceId);
  if (answer.outcome !== "answered") {
    return fail(answer.status, answer.error);
  }
  const data = answer.data;

  if (data.valid !== true) {
    // The one answer that switches Pro off, and it is only ever reached
    // because the service got through to Lemon Squeezy and was told so. A
    // refund or a chargeback disables the key; that is a different thing from
    // a key that was never real, and the client is told which.
    const status = String((data.license_key && data.license_key.status) || "").toLowerCase();
    return fail(403, status === "disabled" ? "revoked" : "invalid");
  }

  const variantId = stringOrEmpty(data.meta && data.meta.variant_id);
  if (variantId !== EXPECTED_VARIANT_ID) {
    // Not invalid. A licence for another product is a real licence, and the
    // likeliest way to arrive here is a new plan added to the store without
    // this constant being updated — at which point answering invalid would
    // cancel Pro for everybody who bought it. This one leaves everything as it
    // was and shows up as an outage instead, which is the failure worth having.
    return fail(403, "wrong_product");
  }

  const instance = data.instance;
  if (stringOrEmpty(instance && instance.id) !== instanceId) {
    // Without this the answer could be about a different activation than the
    // request named — and the name would still match, because it would be the
    // name of whatever instance Lemon Squeezy chose to describe.
    return fail(409, "instance_mismatch");
  }

  // The binding, and the reason a valid key cannot be used to sign for
  // somebody else installation. The name was fixed when the instance was
  // activated and comes back from Lemon Squeezy; the hash in the request is
  // only an input. Rebuilt and compared exactly: no prefix matching, no
  // normalisation, no trimming.
  if (stringOrEmpty(instance && instance.name) !== INSTANCE_NAME_PREFIX + installationHash) {
    return fail(409, "instance_mismatch");
  }

  // ── the receipt ─────────────────────────────────────────────────────
  const issuedAt = new Date();
  const expiresAt = new Date(issuedAt.getTime() + LIFETIME_MS);
  const receipt = {
    receipt_version: RECEIPT_VERSION,
    key_id: KEY_ID,
    audience: AUDIENCE,
    license_id: stringOrEmpty(data.license_key && data.license_key.id),
    instance_id: instanceId,
    variant_id: variantId,
    installation_hash: installationHash,
    issued_at: isoUtc(issuedAt),
    expires_at: isoUtc(expiresAt),
  };
  if (!receipt.license_id) {
    return fail(502, "upstream_unavailable");
  }

  let signed;
  try {
    signed = canonicalBytes(receipt);
  } catch (_err) {
    // A value carrying the separator could spell out a second field inside
    // itself, and two different receipts would sign the same bytes. Refused
    // rather than escaped.
    return fail(502, "upstream_unavailable");
  }

  receipt.signature = toBase64(await sign(signed, env.SIGNING_KEY));
  return json(200, receipt);
}

async function readCappedBody(request, limit) {
  if (!request.body) {
    return new Uint8Array();
  }
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const combined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return combined;
}

// ── Lemon Squeezy ─────────────────────────────────────────────────────
async function validateWithLemon(licenseKey, instanceId) {
  const form = new URLSearchParams();
  form.set("license_key", licenseKey);
  form.set("instance_id", instanceId);

  let response;
  try {
    response = await fetch(LEMON_VALIDATE_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json",
      },
      body: form.toString(),
      signal: AbortSignal.timeout(LEMON_TIMEOUT_MS),
    });
  } catch (_err) {
    return { outcome: "failed", status: 502, error: "upstream_unavailable" };
  }

  if (response.status === 429) {
    // Passed through rather than translated. The client already knows to keep
    // everything and come back later, and calling a rate limit an outage would
    // lose that distinction for no gain.
    return { outcome: "failed", status: 429, error: "rate_limited" };
  }

  // A statement about a licence arrives with a 4xx as readily as a 200: an
  // unknown key comes back 404, which the first version of this treated as an
  // outage, so a mistyped key was answered with "try again later" forever.
  //
  // 5xx is different and stays an outage whatever the body says. A service in
  // trouble can return something that reads like an answer, and believing it
  // would end a licence on the strength of an error page.
  if (response.status !== 200 && (response.status < 400 || response.status >= 500)) {
    return { outcome: "failed", status: 502, error: "upstream_unavailable" };
  }

  let data;
  try {
    data = await response.json();
  } catch (_err) {
    return { outcome: "failed", status: 502, error: "upstream_unavailable" };
  }
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    return { outcome: "failed", status: 502, error: "upstream_unavailable" };
  }
  if (typeof data.valid !== "boolean") {
    // Not an answer about a licence, whatever else it is. Reaching for invalid
    // when confused is how a service ends licences by accident.
    return { outcome: "failed", status: 502, error: "upstream_unavailable" };
  }
  return { outcome: "answered", data };
}

// ── signing ───────────────────────────────────────────────────────────
function canonicalBytes(receipt) {
  const lines = [];
  for (const field of SIGNED_FIELDS) {
    const value = String(receipt[field]);
    if (value.includes("\n")) {
      throw new Error("separator in a signed value");
    }
    lines.push(field + "=" + value);
  }
  return new TextEncoder().encode(lines.join("\n"));
}

let cachedKey = null;

async function sign(bytes, secret) {
  if (cachedKey === null) {
    if (typeof secret !== "string" || !secret) {
      throw new Error("no signing key");
    }
    // PKCS#8 DER, base64. The private half exists here and in whatever safe
    // place a copy was kept, and nowhere else.
    const der = fromBase64(secret.trim());
    cachedKey = await crypto.subtle.importKey("pkcs8", der, { name: "Ed25519" }, false, ["sign"]);
  }
  return new Uint8Array(await crypto.subtle.sign("Ed25519", cachedKey, bytes));
}

// ── odds and ends ─────────────────────────────────────────────────────
function isField(value) {
  return typeof value === "string" && value.length > 0 && value.length <= MAX_FIELD_LENGTH;
}

function stringOrEmpty(value) {
  return value === null || value === undefined ? "" : String(value);
}

function isoUtc(when) {
  // Second precision and a written-out offset. Python fromisoformat reads a Z
  // perfectly well, so this is legibility rather than necessity: a receipt is
  // something a person may end up looking at in a support conversation, and
  // milliseconds on a fortnight are noise.
  return when.toISOString().replace(/\.\d+Z$/, "+00:00");
}

function toBase64(bytes) {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function fromBase64(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function json(status, payload, headers) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: Object.assign(
      {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      },
      headers || {},
    ),
  });
}

function fail(status, error, headers) {
  return json(status, { error: error }, headers);
}
