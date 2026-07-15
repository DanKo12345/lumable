# LumaBLE Local API

LumaBLE can expose a small local HTTP API so Home Assistant, Stream Deck,
AutoHotkey, or your own scripts can control the strip. It is **off by default**,
**loopback-only** (`127.0.0.1`), and protected by a token.

## Enabling it

Open **Settings → Local API** in LumaBLE:

1. Click **Enable**. A token is generated and the status shows
   `Running at http://127.0.0.1:7345`.
2. Click **Copy** to copy the token.
3. (Optional) change the **Port**.
4. (Advanced, dangerous) **Allow LAN access** binds the API to a specific local
   IP so other devices — e.g. a Home Assistant box on another machine — can reach
   it. Leave this off unless you understand the risk, and always set a concrete
   IP (never all interfaces).

Every request except `GET /health` and `GET /` must include:

```
Authorization: Bearer <your-token>
```

The API version is `1` (see `GET /health`). Breaking changes will bump it.

## Endpoints

| Method & path      | Body                     | Description                          |
|--------------------|--------------------------|--------------------------------------|
| `GET /`            | —                        | Index: version + endpoint list (no auth) |
| `GET /health`      | —                        | Version probe (no auth)              |
| `GET /status`      | —                        | Current power / colour / brightness / connection / mode |
| `GET /devices`     | —                        | Connected controllers (address, name, role) |
| `GET /events`      | —                        | Live status stream (Server-Sent Events) |
| `POST /power`      | `{"on": true}`           | Turn the strip on/off (idempotent)   |
| `POST /color`      | `{"r":255,"g":80,"b":0}` | Set an RGB colour (0–255, clamped)   |
| `POST /brightness` | `{"value": 60}`          | Set brightness (0–100)               |
| `POST /effect`     | `{"code": 5, "speed": 70}` | Built-in effect by code; `speed` optional |
| `POST /quick-mode` | `{"key": "gaming"}`      | Activate a quick mode                |

Optional `"device_id": "<address>"` on any command targets a specific strip;
omit it to control the group.

Responses are JSON. Errors look like `{"error": "..."}` with a matching HTTP
status (`400` bad request, `401` unauthorized, `404` not found, `413` too large).

## Examples

Replace `TOKEN` with your copied token. On Windows PowerShell use `curl.exe`
(the bare `curl` is a different alias).

**Health / status**

```
curl.exe http://127.0.0.1:7345/health
curl.exe -H "Authorization: Bearer TOKEN" http://127.0.0.1:7345/status
```

**Turn on, set colour and brightness**

```
curl.exe -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" -d "{\"on\":true}" http://127.0.0.1:7345/power
curl.exe -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" -d "{\"r\":255,\"g\":80,\"b\":0}" http://127.0.0.1:7345/color
curl.exe -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" -d "{\"value\":60}" http://127.0.0.1:7345/brightness
```

**Live stream (Ctrl+C to stop)**

```
curl.exe -N -H "Authorization: Bearer TOKEN" http://127.0.0.1:7345/events
```

**PowerShell (Invoke-RestMethod)**

```powershell
$headers = @{ Authorization = "Bearer TOKEN" }
Invoke-RestMethod http://127.0.0.1:7345/status -Headers $headers
Invoke-RestMethod http://127.0.0.1:7345/power -Method Post -Headers $headers -ContentType "application/json" -Body '{"on":true}'
```

**AutoHotkey v2**

```autohotkey
Power(on) {
    req := ComObject("WinHttp.WinHttpRequest.5.1")
    req.Open("POST", "http://127.0.0.1:7345/power", false)
    req.SetRequestHeader("Authorization", "Bearer TOKEN")
    req.SetRequestHeader("Content-Type", "application/json")
    req.Send('{"on":' (on ? "true" : "false") '}')
}
```

## Home Assistant

See [home-assistant.yaml](home-assistant.yaml) for ready-to-paste
`rest_command` and REST `sensor` snippets. Home Assistant calls the local API
over HTTP — no custom component or cloud needed. Note that if Home Assistant runs
on a **different** machine, you must enable **Allow LAN access** and point the
YAML at this PC's LAN IP instead of `127.0.0.1`.
