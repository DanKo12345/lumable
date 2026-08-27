/**
 * Run the Worker here, without Cloudflare and without Lemon Squeezy.
 *
 * A Worker is a module with a fetch handler, and Node has Request, Response
 * and an Ed25519 that behaves the same way — so the real src/worker.js can be
 * imported and called, with the upstream replaced by something that answers
 * however this file wants it to. That is the only way to see the branches that
 * matter: a refunded licence, an instance belonging to another machine, an API
 * that has gone down mid-sentence. None of them can be produced on demand
 * against the live service, and the ones that can would need a real licence key
 * to reach.
 *
 * It signs with a key made here and thrown away, never the deployed one. The
 * receipt it produces is handed to app/license_receipt.py, which is what says
 * whether any of this actually agrees.
 *
 * Results go to stdout as JSON. tests/test_license_worker_behaviour.py reads
 * them; run it that way rather than by eye.
 */

import worker from "../src/worker.js";

const HASH = "6gMgc3K5w-RS6E8LZVKT6_HcWsMEA7UepSyCrmhaT4k";
const INSTANCE = "inst-uuid-001";
const KEY = "TEST-KEY-0001";
const URL_ISSUE = "https://example.invalid/v1/issue";

// ── a signing key that exists for one run ─────────────────────────────
const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
const pkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
const rawPublic = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
let rateLimitSuccess = true;
const env = {
  SIGNING_KEY: Buffer.from(pkcs8).toString("base64"),
  ISSUE_RATE_LIMITER: {
    async limit() {
      return { success: rateLimitSuccess };
    },
  },
};

// ── a Lemon Squeezy that answers to order ─────────────────────────────
let upstream = null;
let upstreamCalls = 0;
let lastUpstreamBody = null;

globalThis.fetch = async (_url, options) => {
  upstreamCalls += 1;
  lastUpstreamBody = options.body;
  if (typeof upstream === "function") {
    return upstream();
  }
  return new Response(JSON.stringify(upstream.body), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
};

const good = {
  status: 200,
  body: {
    valid: true,
    license_key: { id: 42, status: "active", key: KEY },
    instance: { id: INSTANCE, name: "LumaBLE:" + HASH },
    meta: { variant_id: 1776109, product_id: 1, store_id: 1 },
  },
};

function lemon(patch) {
  const body = structuredClone(good.body);
  patch(body);
  return { status: 200, body };
}

// ── asking ────────────────────────────────────────────────────────────
async function ask(overrides = {}) {
  const {
    method = "POST",
    path = "/v1/issue",
    contentType = "application/json",
    body = { license_key: KEY, instance_id: INSTANCE, installation_hash: HASH },
    rawBody = null,
    contentLength = null,
  } = overrides;

  const headers = {};
  if (contentType !== null) {
    headers["Content-Type"] = contentType;
  }
  if (contentLength !== null) {
    headers["Content-Length"] = String(contentLength);
  }

  const init = { method, headers };
  if (method !== "GET" && method !== "HEAD") {
    init.body = rawBody === null ? JSON.stringify(body) : rawBody;
  }

  const response = await worker.fetch(
    new Request((overrides.scheme || "https://") + "example.invalid" + path, init),
    env,
  );
  let parsed = null;
  try {
    parsed = JSON.parse(await response.text());
  } catch (_err) {
    parsed = null;
  }
  return { status: response.status, body: parsed };
}

const results = {};

async function check(name, setup, overrides) {
  upstream = setup;
  upstreamCalls = 0;
  const answer = await ask(overrides);
  results[name] = { ...answer, upstream_calls: upstreamCalls };
}

// ── the one that works ────────────────────────────────────────────────
upstream = good;
upstreamCalls = 0;
const issued = await ask();
results.issued = { ...issued, upstream_calls: upstreamCalls };
results.upstream_request = lastUpstreamBody;
results.public_key = Buffer.from(rawPublic).toString("base64");

// ── the request, judged before anybody is asked ───────────────────────
await check("plain_http", good, { scheme: "http://" });
await check("wrong_path", good, { path: "/issue" });
await check("wrong_path_versioned", good, { path: "/v1/issue/extra" });
await check("get", good, { method: "GET" });
await check("put", good, { method: "PUT" });
await check("no_content_type", good, { contentType: null });
await check("form_content_type", good, { contentType: "application/x-www-form-urlencoded" });
await check("charset_is_fine", good, { contentType: "application/json; charset=utf-8" });
await check("not_json", good, { rawBody: "{not json" });
await check("json_array", good, { rawBody: "[1,2,3]" });
await check("json_string", good, { rawBody: '"hello"' });

await check("no_key", good, { body: { instance_id: INSTANCE, installation_hash: HASH } });
await check("empty_key", good, {
  body: { license_key: "", instance_id: INSTANCE, installation_hash: HASH },
});
await check("key_too_long", good, {
  body: { license_key: "x".repeat(201), instance_id: INSTANCE, installation_hash: HASH },
});
await check("key_not_a_string", good, {
  body: { license_key: 12345, instance_id: INSTANCE, installation_hash: HASH },
});
await check("no_instance", good, { body: { license_key: KEY, installation_hash: HASH } });
await check("hash_too_short", good, {
  body: { license_key: KEY, instance_id: INSTANCE, installation_hash: HASH.slice(0, 42) },
});
await check("hash_too_long", good, {
  body: { license_key: KEY, instance_id: INSTANCE, installation_hash: HASH + "a" },
});
await check("hash_wrong_alphabet", good, {
  body: { license_key: KEY, instance_id: INSTANCE, installation_hash: "+" + HASH.slice(1) },
});
await check("hash_with_padding", good, {
  body: { license_key: KEY, instance_id: INSTANCE, installation_hash: HASH.slice(0, 42) + "=" },
});
await check("hash_not_a_string", good, {
  body: { license_key: KEY, instance_id: INSTANCE, installation_hash: null },
});

// A body over the limit, and a header that lies about one that is not.
await check("oversized_body", good, {
  rawBody: JSON.stringify({
    license_key: KEY,
    instance_id: INSTANCE,
    installation_hash: HASH,
    padding: "x".repeat(5000),
  }),
});
await check("oversized_header", good, { contentLength: 99999 });
rateLimitSuccess = false;
await check("client_rate_limited", good, {});
rateLimitSuccess = true;

// ── what Lemon Squeezy says ───────────────────────────────────────────
await check("not_valid", lemon((b) => {
  b.valid = false;
  b.license_key.status = "inactive";
}));
await check("disabled", lemon((b) => {
  b.valid = false;
  b.license_key.status = "disabled";
}));
await check("expired", lemon((b) => {
  b.valid = false;
  b.license_key.status = "expired";
}));
await check("not_valid_no_status", { status: 400, body: { valid: false, error: "not found" } });
// What an unknown key actually comes back as. Confirmed against the live API,
// where it is a 404 and not the 400 this once assumed.
await check("unknown_key_404", { status: 404, body: { valid: false, error: "license_key not found." } });
await check("forbidden_403", { status: 403, body: { valid: false, license_key: { status: "disabled" } } });
await check("gone_410", { status: 410, body: { valid: false, license_key: { status: "inactive" } } });

await check("wrong_variant", lemon((b) => {
  b.meta.variant_id = 999;
}));
await check("no_variant", lemon((b) => {
  delete b.meta.variant_id;
}));
await check("another_instance_described", lemon((b) => {
  b.instance.id = "inst-somebody-else";
}));
await check("another_machine_name", lemon((b) => {
  b.instance.name = "LumaBLE:" + "A".repeat(43);
}));
await check("name_without_prefix", lemon((b) => {
  b.instance.name = HASH;
}));
await check("name_with_prefix_only", lemon((b) => {
  b.instance.name = "LumaBLE:";
}));
await check("name_padded", lemon((b) => {
  b.instance.name = " LumaBLE:" + HASH + " ";
}));
await check("no_instance_at_all", lemon((b) => {
  delete b.instance;
}));
await check("no_license_id", lemon((b) => {
  delete b.license_key.id;
}));

await check("upstream_500", { status: 500, body: { error: "boom" } });
// A service in trouble whose body happens to read like an answer. Without the
// status being looked at, this alone would end somebody licence.
await check("upstream_500_that_parses", {
  status: 500,
  body: { valid: false, license_key: { status: "inactive" } },
});
await check("upstream_502_that_parses", {
  status: 502,
  body: { valid: false, license_key: { status: "disabled" } },
});
await check("upstream_503", { status: 503, body: {} });
await check("upstream_429", { status: 429, body: { error: "too many" } });
await check("upstream_html", () => new Response("<html>down</html>", { status: 200 }));
await check("upstream_no_valid_field", { status: 200, body: { license_key: { id: 1 } } });
await check("upstream_valid_is_a_string", { status: 200, body: { valid: "true" } });
await check("upstream_refused", () => {
  throw new Error("connection refused");
});

process.stdout.write(JSON.stringify(results, null, 2));
