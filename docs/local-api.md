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
| `GET /status`      | —                        | Current power / colour / brightness / connection, plus `name`, `effect`, `mode`, `pc_mode`, `pc_mode_preset`, `pc_mode_detail` |
| `GET /devices`     | —                        | Connected controllers (address, name, role) |
| `GET /events`      | —                        | Live status stream (Server-Sent Events) |
| `POST /power`      | `{"on": true}`           | Turn the strip on/off (idempotent)   |
| `POST /color`      | `{"r":255,"g":80,"b":0}` | Set an RGB colour (0–255, clamped)   |
| `POST /brightness` | `{"value": 60}`          | Set brightness (0–100)               |
| `POST /effect`     | `{"code": 5, "speed": 70}` | Built-in effect by code; `speed` optional |
| `POST /quick-mode` | `{"key": "gaming"}`      | Activate a quick mode                |
| `POST /pc-mode`    | `{"mode": "screen"}`     | Start a PC mode (`screen`/`music`/`effect`/`diy`) or `off` to stop |
| `GET /scenes`      | —                        | List saved scenes                    |
| `POST /scenes/save`| `{"name": "Movie"}`      | Snapshot the current look as a scene |
| `POST /scenes/apply`| `{"scene_id": "..."}`   | Apply a saved scene                  |
| `POST /scenes/delete`| `{"scene_id": "..."}` | Delete a saved scene                 |

Optional `"device_id": "<address>"` on any command targets **one** strip; omit it
to drive every connected strip. An addressed write goes only to that controller
and does not move the desktop sliders — unless the address is the primary strip,
whose state the app's UI and `/status` represent.

Responses are JSON. Errors look like `{"error": "..."}` with a matching HTTP
status (`400` bad request, `401` unauthorized, `404` not found, `409` conflict,
`413` too large).

## PC modes and scenes

`POST /pc-mode` starts a mode that runs **on the PC** and drives the strip —
`screen` (screen sync), `music` (music reaction), `effect` (software effect) or
`diy` (a DIY animation) — and `{"mode":"off"}` stops any of them. If the mode
can't start (needs Pro, or no strip is connected) the call returns `409`, not a
false success. `/status` reports the active one in `pc_mode` (with a readable
`pc_mode_detail`, e.g. the running effect's name). For Screen Sync,
`pc_mode_preset` contains the stable response-profile id (`desktop`, `game` or
`movie`); it is `null` for other modes.

Scenes are one saved look — power, colour, brightness, a built-in effect and an
optional PC mode — shared by the desktop app, the phone remote and this API.
`POST /scenes/save` snapshots the current state under a name (re-using the same
name overwrites it); `GET /scenes` lists them with their `scene_id`;
`POST /scenes/apply` recalls one. In this release a scene applies to every
connected strip (per-strip targeting arrives in a later update).

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
