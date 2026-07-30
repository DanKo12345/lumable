"""Self-contained, translated phone remote served by the local API.

The page deliberately stays a fast control surface rather than duplicating the
desktop app: power, brightness, colour and quick modes.  It contains no remote
assets and receives its visible strings from the language selected in LumaBLE.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

_FALLBACK_LABELS = {
    "pair_title": "Connect your phone",
    "pair_prompt": "Enter the pairing code shown in LumaBLE on your PC.",
    "pair_connect": "Connect",
    "pair_invalid": "Wrong or expired code.",
    "pair_failed": "Could not connect.",
    "connected": "Connected",
    "disconnected": "Strip not connected",
    "power_on": "On",
    "power_off": "Off",
    "all_off": "Turn everything off",
    "pc_modes": "PC modes",
    "pc_screen": "Screen",
    "pc_music": "Music",
    "pc_effect": "Effect",
    "pc_diy": "DIY",
    "pc_active": "active",
    "pc_stop": "Stop",
    "scenes": "Scenes",
    "save_scene": "Save current",
    "scenes_empty": "No scenes yet",
    "scene_name_prompt": "Scene name",
    "scene_saved": "Saved",
    "brightness": "Brightness",
    "colour": "Colour",
    "quick_modes": "Quick modes",
    "current_colour": "Current colour",
    "custom_colour": "Custom colour",
    "recent_colours": "Recent",
    "open_palette": "Choose any colour",
    "close_palette": "Hide palette",
    "sent": "Sent",
    "send_failed": "No connection",
    "mode_unavailable": "Mode unavailable: connect a strip or activate Pro",
    "mode_chill": "Chill",
    "mode_gaming": "Gaming",
    "mode_night": "Night",
    "mode_rainbow": "Rainbow",
}


_TEMPLATE = """<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>LumaBLE</title>
<style>
  :root {
    --bg:#0c0e13; --surface:#171a22; --surface-hi:#20242e; --field:#11141b;
    --line:#303641; --line-soft:rgba(255,255,255,.075);
    --text:#f5f6f8; --text-soft:#d7dbe4; --muted:#9199aa;
    --accent:#8fbfff; --accent-soft:rgba(143,191,255,.14);
    --live:rgb(143,191,255); --ok:#58d6aa; --warn:#eeb65d; --danger:#ff8392;
    --radius:18px;
  }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  html { background:var(--bg); scroll-behavior:smooth; }
  body {
    margin:0; min-width:280px; min-height:100dvh; background:var(--bg); color:var(--text);
    font:15px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    padding:0 16px calc(112px + env(safe-area-inset-bottom));
  }
  .shell { width:100%; max-width:460px; margin:0 auto; }
  header {
    position:sticky; top:0; z-index:6; display:flex; align-items:center; justify-content:space-between;
    min-height:82px; margin:0 -4px 14px; padding:max(18px,env(safe-area-inset-top)) 4px 12px;
    background:linear-gradient(180deg,var(--bg) 70%,rgba(12,14,19,0));
  }
  h1 { margin:0; font-size:25px; line-height:1; letter-spacing:0; font-weight:800; }
  .device-line { display:flex; align-items:center; gap:7px; min-height:18px; margin-top:7px; color:var(--muted); font-size:12px; font-weight:650; }
  .device-line span + span::before { content:"·"; margin-right:7px; color:var(--line); }
  .device-line .hide + span::before { display:none; }
  .pairing .device-line, .pairing header > .dot { visibility:hidden; }
  .card {
    background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
    padding:16px; margin-bottom:12px; animation:rise .28s both;
  }
  #remote .card:nth-child(1) { animation-delay:.02s; } #remote .card:nth-child(2) { animation-delay:.05s; }
  #remote .card:nth-child(3) { animation-delay:.08s; } #remote .card:nth-child(4) { animation-delay:.11s; }
  #remote .card:nth-child(5) { animation-delay:.14s; }
  @keyframes rise { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:none; } }
  .label, .muted { color:var(--muted); font-size:13px; }
  .section-heading, .value-line { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:13px; }
  .section-title { color:var(--text-soft); font-size:14px; font-weight:750; }
  .heading-copy { display:flex; align-items:center; gap:9px; min-width:0; }
  .mini-icon { width:19px; height:19px; color:var(--muted); flex:0 0 19px; }
  .mini-icon svg { display:block; width:100%; height:100%; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }
  .dot { width:10px; height:10px; flex:0 0 10px; border-radius:50%; background:var(--warn); transition:background .2s,box-shadow .2s; }
  .dot.on { background:var(--ok); box-shadow:0 0 12px rgba(72,214,160,.7); }
  .dot.off { background:var(--warn); }
  button {
    font:inherit; color:var(--text); min-height:46px; background:var(--surface-hi);
    border:1px solid var(--line); border-radius:14px; padding:10px 12px;
    transition:background .16s,border-color .16s,transform .09s,box-shadow .16s;
  }
  button:active { transform:scale(.975); } button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .row { display:flex; gap:10px; } .row > * { flex:1; }
  .sel { background:var(--accent-soft); border-color:var(--accent); box-shadow:inset 0 0 0 1px var(--accent); font-weight:700; }
  .power-on.sel { border-color:var(--ok); background:rgba(72,214,160,.14); box-shadow:inset 0 0 0 1px var(--ok); }
  .power-off.sel { border-color:var(--warn); background:rgba(244,187,94,.13); box-shadow:inset 0 0 0 1px var(--warn); }
  input { font:inherit; color:var(--text); background:var(--field); border:1px solid var(--line); border-radius:14px; padding:14px; width:100%; }
  #code { min-height:58px; text-align:center; letter-spacing:.34em; font-size:21px; font-variant-numeric:tabular-nums; }
  input[type=range] { appearance:none; -webkit-appearance:none; height:28px; padding:0; border:0; background:transparent; }
  input[type=range]::-webkit-slider-runnable-track { height:6px; border-radius:99px; background:linear-gradient(90deg,var(--live) 0 var(--range,100%),var(--field) var(--range,100%) 100%); border:1px solid var(--line); }
  input[type=range]::-webkit-slider-thumb { appearance:none; -webkit-appearance:none; width:24px; height:24px; margin-top:-10px; border-radius:50%; border:3px solid var(--text); background:var(--live); box-shadow:0 2px 8px rgba(0,0,0,.42); }
  input[type=range]::-moz-range-track { height:6px; border-radius:99px; background:var(--field); border:1px solid var(--line); }
  input[type=range]::-moz-range-progress { height:6px; border-radius:99px; background:var(--live); }
  input[type=range]::-moz-range-thumb { width:18px; height:18px; border-radius:50%; border:3px solid var(--text); background:var(--live); }
  .value { color:var(--text); font-weight:700; font-variant-numeric:tabular-nums; }
  .divider { height:1px; margin:14px 0; background:var(--line-soft); }
  .colour-head { display:flex; align-items:center; gap:11px; margin-bottom:14px; }
  .colour-chip { width:34px; height:34px; border-radius:11px; background:var(--live); border:1px solid rgba(255,255,255,.38); box-shadow:0 0 16px color-mix(in srgb,var(--live) 42%,transparent); transition:background .2s,box-shadow .2s; }
  .hex { color:var(--text); font-weight:750; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing:.04em; }
  .grid { display:grid; gap:9px; }
  .swatches { grid-template-columns:repeat(4,52px); justify-content:space-between; }
  .sw { width:52px; height:52px; min-height:0; padding:0; border-radius:14px; border:1px solid var(--line); }
  .sw.sel { box-shadow:0 0 0 3px var(--bg),0 0 0 5px var(--text); transform:scale(.94); }
  .modes { grid-template-columns:repeat(2,1fr); }
  .pc { grid-template-columns:repeat(2,1fr); }
  .pc button.sel { border-color:var(--live); background:color-mix(in srgb, var(--live) 18%, transparent); box-shadow:inset 0 0 0 1px var(--live); }
  .pc-active { display:flex; align-items:center; gap:12px; margin-top:12px; }
  .pc-active .pc-active-text { flex:1; color:var(--text); font-weight:650; font-size:13px; line-height:1.3; }
  .pc-active .pc-active-text b { color:var(--live); }
  #pcStop { flex:0 0 auto; min-height:40px; padding:8px 15px; border-color:var(--warn); color:var(--warn); }
  .quiet { width:100%; min-height:40px; margin-top:9px; padding:7px; color:var(--muted); background:transparent; border-color:transparent; }
  .chip-btn { width:auto; min-height:36px; padding:7px 12px; color:var(--text-soft); font-size:13px; }
  .scenes { display:flex; flex-direction:column; gap:8px; }
  .scene-row { display:flex; gap:8px; }
  .scene-apply { flex:1; text-align:left; font-weight:650; display:flex; align-items:center; gap:10px; }
  .scene-dot { width:14px; height:14px; flex:0 0 14px; border-radius:5px; border:1px solid rgba(255,255,255,.25); }
  .scene-del { flex:0 0 auto; width:46px; min-height:46px; color:var(--muted); }
  .scenes .muted { padding:6px 2px; }
  .palette-toggle { width:100%; min-height:42px; margin-top:12px; color:var(--muted); background:transparent; }
  .palette-toggle[aria-expanded="true"] { color:var(--text); border-color:var(--accent); background:var(--accent-soft); }
  .picker {
    max-height:0; margin-top:0; overflow:hidden; opacity:0; transform:translateY(-8px) scale(.985);
    visibility:hidden; pointer-events:none;
    transition:max-height .30s cubic-bezier(.22,.8,.25,1),margin-top .30s cubic-bezier(.22,.8,.25,1),opacity .18s ease,transform .30s cubic-bezier(.22,.8,.25,1),visibility 0s linear .30s;
  }
  .picker.open { max-height:310px; margin-top:14px; opacity:1; transform:none; visibility:visible; pointer-events:auto; transition-delay:0s; }
  .picker-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
  canvas {
    display:block; width:100%; height:190px; border:1px solid var(--line); border-radius:14px;
    touch-action:none; cursor:crosshair; background:#fff;
  }
  .hue { height:28px; margin:14px 0 0; }
  .hue::-webkit-slider-runnable-track { height:12px; border:0; background:linear-gradient(90deg,#f33,#ffeb3b,#28d878,#19a9ff,#7045ff,#ef27b8,#f33); }
  .hue::-webkit-slider-thumb { width:24px; height:24px; margin-top:-6px; border:3px solid #fff; background:transparent; }
  .hue::-moz-range-track { height:12px; border:0; background:linear-gradient(90deg,#f33,#ffeb3b,#28d878,#19a9ff,#7045ff,#ef27b8,#f33); }
  .hue::-moz-range-progress { background:transparent; }
  .hue::-moz-range-thumb { width:18px; height:18px; border:3px solid #fff; background:transparent; }
  .recent-label { margin:14px 0 9px; }
  #recent { grid-template-columns:repeat(5,42px); justify-content:space-between; }
  #recent .sw { width:42px; height:42px; border-radius:12px; }
  #pair { margin-top:clamp(24px,9vh,82px); padding:22px; }
  .pair-mark { display:grid; place-items:center; width:48px; height:48px; margin-bottom:18px; color:var(--accent); background:var(--accent-soft); border:1px solid rgba(143,191,255,.28); border-radius:15px; }
  .pair-mark svg { width:24px; height:24px; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }
  .pair-title { margin:0 0 6px; font-size:20px; font-weight:800; }
  #pairPrompt { margin:0 0 18px; line-height:1.5; }
  #pairButton { width:100%; margin-top:12px; color:#102035; background:var(--accent); border-color:transparent; font-weight:800; }
  #pairError { min-height:20px; margin-top:10px; color:var(--danger); font-size:13px; }
  .toast {
    position:fixed; left:50%; bottom:calc(92px + env(safe-area-inset-bottom)); transform:translate(-50%,14px);
    background:var(--surface-hi); border:1px solid var(--line); color:var(--text);
    padding:10px 18px; border-radius:18px; font-size:14px; font-weight:650;
    max-width:calc(100% - 36px); text-align:center; line-height:1.35;
    opacity:0; pointer-events:none; transition:opacity .18s,transform .18s; box-shadow:0 8px 26px rgba(0,0,0,.4); z-index:9;
  }
  .toast.show { opacity:1; transform:translate(-50%,0); }
  .toast.error { border-color:var(--warn); color:var(--warn); }
  .hide { display:none!important; }
  .busy button { pointer-events:none; opacity:.72; }
  @media (max-width:350px) {
    body { padding-left:12px; padding-right:12px; }
    .card { padding:14px; }
    .swatches { grid-template-columns:repeat(4,46px); }
    .sw { width:46px; height:46px; }
  }
  @media (prefers-color-scheme:light) {
    :root {
      --bg:#f1f3f6; --surface:#fff; --surface-hi:#f6f7fa; --field:#eef1f5;
      --line:#cfd5df; --line-soft:rgba(30,40,58,.09); --text:#171a20;
      --text-soft:#353b47; --muted:#6f7889; --accent-soft:rgba(74,124,218,.13);
    }
    header { background:linear-gradient(180deg,var(--bg) 70%,rgba(241,243,246,0)); }
    .sw.sel { box-shadow:0 0 0 3px var(--bg),0 0 0 5px #273044; }
  }
  @media (prefers-reduced-motion:reduce) { *,*::before,*::after { animation-duration:.01ms!important; transition-duration:.01ms!important; scroll-behavior:auto!important; } }
</style>
</head>
<body>
<main class="shell">
  <header>
    <div><h1>LumaBLE</h1><div class="device-line"><span class="hide" id="deviceName"></span><span id="status" aria-live="polite">...</span></div></div>
    <span class="dot" id="conn" aria-hidden="true"></span>
  </header>

  <section id="pair" class="card hide">
    <div class="pair-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg></div>
    <h2 class="pair-title" id="pairTitle"></h2>
    <div class="muted" id="pairPrompt"></div>
    <input id="code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="000000" aria-label="Pairing code">
    <button id="pairButton" onclick="pair()"></button>
    <div id="pairError" aria-live="polite"></div>
  </section>

  <section id="remote" class="hide">
    <section class="card">
      <div class="row"><button class="power-on" id="btnOn" onclick="power(true)"></button><button class="power-off" id="btnOff" onclick="power(false)"></button></div>
      <button class="quiet" id="btnAllOff" onclick="masterOff()"></button>
      <div class="divider"></div>
      <div class="value-line"><div class="heading-copy"><span class="mini-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></span><span class="section-title" id="brightnessLabel"></span></div><span class="value" id="brightnessValue">100%</span></div>
      <input type="range" id="bri" min="0" max="100" value="100" oninput="queueBrightness(this.value)">
    </section>
    <section class="card">
      <div class="colour-head"><span class="colour-chip" id="colourChip"></span><div><div class="label" id="colourLabel"></div><div class="hex" id="hex">#FFFFFF</div></div></div>
      <div class="grid swatches" id="swatches"></div><div class="label recent-label hide" id="recentLabel"></div><div class="grid hide" id="recent"></div>
      <button class="palette-toggle" id="paletteToggle" aria-expanded="false" aria-controls="picker" onclick="togglePalette()"></button>
      <div class="picker" id="picker" aria-hidden="true"><div class="picker-head"><span class="section-title" id="customColourLabel"></span><span class="hex" id="pickerHex">#FFFFFF</span></div><canvas id="sv" aria-label="Colour palette"></canvas><input class="hue" id="hue" type="range" min="0" max="360" value="0" oninput="setHue(this.value)"></div>
    </section>
    <section class="card"><div class="section-heading"><div class="heading-copy"><span class="mini-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m12 3-1.9 4.3L6 9.2l4.1 1.9L12 15l1.9-3.9L18 9.2l-4.1-1.9L12 3z"/><path d="m19 15-.9 2.1L16 18l2.1.9L19 21l.9-2.1L22 18l-2.1-.9L19 15z"/></svg></span><span class="section-title" id="modesLabel"></span></div></div><div class="grid modes" id="modes"></div></section>
    <section class="card"><div class="section-heading"><div class="heading-copy"><span class="mini-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 5h16v14H4z"/><path d="M4 9h16"/></svg></span><span class="section-title" id="scenesLabel"></span></div><button class="chip-btn" id="saveScene" onclick="saveScene()"></button></div><div class="scenes" id="scenes"></div></section>
    <section class="card"><div class="section-heading"><div class="heading-copy"><span class="mini-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg></span><span class="section-title" id="pcLabel"></span></div></div><div class="grid pc" id="pcModes"></div><div class="pc-active hide" id="pcActive"><span class="pc-active-text" id="pcActiveText"></span><button id="pcStop" onclick="pcMode('off')"></button></div></section>
  </section>
  <div id="toast" class="toast" role="status" aria-live="polite"></div>
</main>

<script>
const TEXT = __TEXT__;
const $ = s => document.querySelector(s);
let token = localStorage.getItem("lumable_session") || "";
let brightnessTimer = 0;
let pendingBrightness = null;
let colourTimer = 0;
let pendingColour = null;
let paletteOpen = false;
let pickerHue = 0;
let pickerSaturation = 1;
let pickerValue = 1;
let pickerDragging = false;

function text() {
  $("#pairTitle").textContent = TEXT.pair_title;
  $("#pairPrompt").textContent = TEXT.pair_prompt;
  $("#pairButton").textContent = TEXT.pair_connect;
  $("#btnOn").textContent = TEXT.power_on;
  $("#btnOff").textContent = TEXT.power_off;
  $("#brightnessLabel").textContent = TEXT.brightness;
  $("#colourLabel").textContent = TEXT.current_colour;
  $("#modesLabel").textContent = TEXT.quick_modes;
  $("#customColourLabel").textContent = TEXT.custom_colour;
  $("#recentLabel").textContent = TEXT.recent_colours;
  $("#pcLabel").textContent = TEXT.pc_modes;
  $("#btnAllOff").textContent = TEXT.all_off;
  $("#pcStop").textContent = TEXT.pc_stop;
  $("#scenesLabel").textContent = TEXT.scenes;
  $("#saveScene").textContent = TEXT.save_scene;
  updatePaletteToggle();
}
function show(paired) {
  document.body.classList.toggle("pairing", !paired);
  $("#pair").classList.toggle("hide", paired);
  $("#remote").classList.toggle("hide", !paired);
}
async function api(path, opts) {
  opts = opts || {}; opts.headers = Object.assign({"Authorization":"Bearer " + token}, opts.headers || {});
  const response = await fetch(path, opts);
  if (response.status === 401) { token=""; localStorage.removeItem("lumable_session"); show(false); throw new Error("unauthorized"); }
  if (!response.ok) { const error=new Error("request failed"); error.status=response.status; throw error; }
  return response;
}
async function post(path, body, quiet) {
  document.body.classList.add("busy");
  try {
    const response = await api(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    if (!quiet) flash(TEXT.sent, false); return response;
  } catch (error) { if (!quiet) flash(TEXT.send_failed, true); throw error; }
  finally { document.body.classList.remove("busy"); }
}
async function pair() {
  const code = $("#code").value.trim(); $("#pairError").textContent = "";
  try {
    const response = await fetch("/pair", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({code})});
    if (!response.ok) { $("#pairError").textContent = TEXT.pair_invalid; return; }
    const data = await response.json(); token=data.session; localStorage.setItem("lumable_session", token); show(true); startLive(); loadScenes();
  } catch (_) { $("#pairError").textContent = TEXT.pair_failed; }
}
let toastTimer=0;
function flash(message, error) {
  const toast=$("#toast"); toast.textContent=message; toast.classList.toggle("error", !!error); toast.classList.add("show");
  clearTimeout(toastTimer); toastTimer=setTimeout(() => toast.classList.remove("show"), message.length > 24 ? 2600 : 1400);
}
let recent=[];
try { recent=JSON.parse(localStorage.getItem("lumable_recent") || "[]"); } catch (_) { recent=[]; }
function pushRecent(r,g,b) {
  const key=[r,g,b].join(","); recent=recent.filter(c => c.join(",") !== key); recent.unshift([r,g,b]); recent=recent.slice(0,5);
  try { localStorage.setItem("lumable_recent", JSON.stringify(recent)); } catch (_) {}
  renderRecent();
}
function renderRecent() {
  const row=$("#recent"), label=$("#recentLabel"), has=recent.length > 0;
  row.classList.toggle("hide", !has); label.classList.toggle("hide", !has);
  row.innerHTML=recent.map(c => `<button class="sw" data-rgb="${c.join(',')}" style="background:rgb(${c[0]},${c[1]},${c[2]})" onclick="setColor(${c[0]},${c[1]},${c[2]})"></button>`).join("");
}
async function power(on) { await post("/power", {on}); setTimeout(refresh, 120); }
function queueBrightness(value) {
  pendingBrightness = Number(value); $("#brightnessValue").textContent = pendingBrightness + "%";
  $("#bri").style.setProperty("--range", pendingBrightness + "%");
  clearTimeout(brightnessTimer); brightnessTimer = setTimeout(flushBrightness, 120);
}
async function flushBrightness() { if (pendingBrightness === null) return; const value=pendingBrightness; pendingBrightness=null; await post("/brightness", {value}); }
async function setColor(r,g,b) {
  paintColour(r,g,b,true); pushRecent(r,g,b); await post("/color", {r,g,b}); setTimeout(refresh, 120);
}
async function quick(key) { await post("/quick-mode", {key}); setTimeout(refresh, 160); }
async function pcMode(mode) {
  try {
    await post("/pc-mode", {mode}, true);  // handle our own messaging below
    flash(TEXT.sent, false);
  } catch (error) {
    // 409 = the desktop refused (Free licence or no strip); anything else = network.
    flash(error && error.status === 409 ? TEXT.mode_unavailable : TEXT.send_failed, true);
  }
  setTimeout(refresh, 200);
}
async function masterOff() { try { await post("/pc-mode", {mode:"off"}, true); } catch (_) {} await post("/power", {on:false}); setTimeout(refresh, 160); }
let scenes=[];
function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
async function loadScenes() {
  try { const data=await (await api("/scenes")).json(); scenes=data.scenes || []; renderScenes(); } catch (_) {}
}
function renderScenes() {
  const el=$("#scenes");
  if (!scenes.length) { el.innerHTML=`<div class="muted">${TEXT.scenes_empty}</div>`; return; }
  // The id goes in a data attribute (not an inline handler) and a delegated
  // listener reads it, so a scene id can never break out into markup/JS.
  el.innerHTML=scenes.map(s => `<div class="scene-row"><button class="scene-apply" data-scene-id="${escapeHtml(s.scene_id)}"><span class="scene-dot" style="background:${(s.color && escapeHtml(s.color)) || 'var(--line)'}"></span>${escapeHtml(s.name)}</button><button class="scene-del" data-scene-id="${escapeHtml(s.scene_id)}" aria-label="delete">&#10005;</button></div>`).join("");
}
function installScenes() {
  $("#scenes").addEventListener("click", event => {
    const apply=event.target.closest(".scene-apply");
    if (apply) { applyScene(apply.dataset.sceneId); return; }
    const del=event.target.closest(".scene-del");
    if (del) deleteScene(del.dataset.sceneId);
  });
}
async function applyScene(id) {
  try { await post("/scenes/apply", {scene_id:id}, true); flash(TEXT.sent, false); } catch (_) { flash(TEXT.send_failed, true); }
  setTimeout(refresh, 200);
}
async function saveScene() {
  const name=(prompt(TEXT.scene_name_prompt) || "").trim(); if (!name) return;
  try { await post("/scenes/save", {name}, true); flash(TEXT.scene_saved, false); loadScenes(); } catch (_) { flash(TEXT.send_failed, true); }
}
async function deleteScene(id) {
  try { await post("/scenes/delete", {scene_id:id}, true); loadScenes(); } catch (_) { flash(TEXT.send_failed, true); }
}
function rgbHex(r,g,b) { return "#" + [r,g,b].map(v => Number(v).toString(16).padStart(2,"0")).join("").toUpperCase(); }
function paintColour(r,g,b, syncPicker) {
  const value = `rgb(${r},${g},${b})`; document.documentElement.style.setProperty("--live", value);
  const hex=rgbHex(r,g,b); $("#colourChip").style.background=value; $("#hex").textContent=hex; $("#pickerHex").textContent=hex;
  if (syncPicker && !pickerDragging) setPickerFromRgb(r,g,b);
}
function rgbToHsv(r,g,b) {
  r/=255; g/=255; b/=255; const max=Math.max(r,g,b), min=Math.min(r,g,b), delta=max-min;
  let hue=0; if (delta) { if (max===r) hue=60*(((g-b)/delta)%6); else if (max===g) hue=60*((b-r)/delta+2); else hue=60*((r-g)/delta+4); }
  return [((hue+360)%360), max ? delta/max : 0, max];
}
function hsvToRgb(h,s,v) {
  const c=v*s, x=c*(1-Math.abs((h/60)%2-1)), m=v-c; let r=0,g=0,b=0;
  if (h<60) [r,g,b]=[c,x,0]; else if (h<120) [r,g,b]=[x,c,0]; else if (h<180) [r,g,b]=[0,c,x]; else if (h<240) [r,g,b]=[0,x,c]; else if (h<300) [r,g,b]=[x,0,c]; else [r,g,b]=[c,0,x];
  return [Math.round((r+m)*255),Math.round((g+m)*255),Math.round((b+m)*255)];
}
function setPickerFromRgb(r,g,b) {
  [pickerHue,pickerSaturation,pickerValue]=rgbToHsv(r,g,b); $("#hue").value=Math.round(pickerHue); drawPicker();
}
function drawPicker() {
  const canvas=$("#sv"); if (!canvas) return; const rect=canvas.getBoundingClientRect(); const dpr=window.devicePixelRatio||1;
  const width=Math.max(1,Math.round(rect.width*dpr)), height=Math.max(1,Math.round(rect.height*dpr));
  if (canvas.width!==width || canvas.height!==height) { canvas.width=width; canvas.height=height; }
  const ctx=canvas.getContext("2d"); ctx.setTransform(dpr,0,0,dpr,0,0); const w=rect.width, h=rect.height;
  ctx.fillStyle=`hsl(${pickerHue},100%,50%)`; ctx.fillRect(0,0,w,h);
  const white=ctx.createLinearGradient(0,0,w,0); white.addColorStop(0,"#fff"); white.addColorStop(1,"rgba(255,255,255,0)"); ctx.fillStyle=white; ctx.fillRect(0,0,w,h);
  const black=ctx.createLinearGradient(0,0,0,h); black.addColorStop(0,"rgba(0,0,0,0)"); black.addColorStop(1,"#000"); ctx.fillStyle=black; ctx.fillRect(0,0,w,h);
  const x=pickerSaturation*w, y=(1-pickerValue)*h; ctx.beginPath(); ctx.arc(x,y,10,0,Math.PI*2); ctx.strokeStyle="rgba(0,0,0,.56)"; ctx.lineWidth=4; ctx.stroke(); ctx.beginPath(); ctx.arc(x,y,8,0,Math.PI*2); ctx.strokeStyle="#fff"; ctx.lineWidth=2; ctx.stroke();
}
function updatePicker(event) {
  const rect=$("#sv").getBoundingClientRect(); pickerSaturation=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)); pickerValue=1-Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height));
  const rgb=hsvToRgb(pickerHue,pickerSaturation,pickerValue); paintColour(rgb[0],rgb[1],rgb[2],false); drawPicker(); queueColour(rgb);
}
function setHue(value) { pickerHue=Number(value); const rgb=hsvToRgb(pickerHue,pickerSaturation,pickerValue); paintColour(rgb[0],rgb[1],rgb[2],false); drawPicker(); queueColour(rgb); }
function queueColour(rgb) { pendingColour=rgb; clearTimeout(colourTimer); colourTimer=setTimeout(flushColour,120); }
async function flushColour() { if (!pendingColour) return; const [r,g,b]=pendingColour; pendingColour=null; pushRecent(r,g,b); await post("/color", {r,g,b}); }
function updatePaletteToggle() {
  const toggle=$("#paletteToggle"), picker=$("#picker");
  toggle.textContent=paletteOpen ? TEXT.close_palette : TEXT.open_palette;
  toggle.setAttribute("aria-expanded", String(paletteOpen));
  picker.setAttribute("aria-hidden", String(!paletteOpen));
}
function togglePalette() {
  paletteOpen=!paletteOpen; $("#picker").classList.toggle("open",paletteOpen); updatePaletteToggle();
  if (paletteOpen) requestAnimationFrame(() => requestAnimationFrame(drawPicker));
}
function installPicker() {
  const canvas=$("#sv");
  canvas.addEventListener("pointerdown", event => { pickerDragging=true; canvas.setPointerCapture(event.pointerId); updatePicker(event); });
  canvas.addEventListener("pointermove", event => { if (pickerDragging) updatePicker(event); });
  canvas.addEventListener("pointerup", () => { pickerDragging=false; });
  canvas.addEventListener("pointercancel", () => { pickerDragging=false; });
  window.addEventListener("resize", () => { if (paletteOpen) drawPicker(); });
}
async function refresh() {
  try { applyState(await (await api("/status")).json()); } catch (_) {}
}
function applyState(state) {
  const connected=!!state.connected, power=!!state.power, brightness=Number(state.brightness || 0);
  const sub=$("#deviceName"); sub.textContent=state.name || ""; sub.classList.toggle("hide", !state.name);
  $("#conn").className="dot " + (connected ? "on" : "off");
  $("#status").textContent = connected ? `${TEXT.connected} · ${power ? TEXT.power_on : TEXT.power_off} · ${brightness}%` : TEXT.disconnected;
  if (pendingBrightness === null) {
    $("#bri").value=brightness; $("#bri").style.setProperty("--range", brightness + "%");
    $("#brightnessValue").textContent=brightness + "%";
  }
  $("#btnOn").classList.toggle("sel", power); $("#btnOff").classList.toggle("sel", !power);
  const color=state.color || {r:255,g:255,b:255}; if (!pendingColour) paintColour(color.r,color.g,color.b,true);
  const current=[color.r,color.g,color.b].join(",");
  document.querySelectorAll(".sw").forEach(button => button.classList.toggle("sel", power && button.dataset.rgb===current));
  document.querySelectorAll("#modes button").forEach(button => button.classList.toggle("sel", button.dataset.mode===(state.mode || "")));
  const pc=state.pc_mode || "";
  document.querySelectorAll("#pcModes button").forEach(button => button.classList.toggle("sel", button.dataset.pc===pc));
  $("#pcActive").classList.toggle("hide", !pc);
  if (pc) {
    const name=TEXT['pc_'+pc] || pc, detail=state.pc_mode_detail || "";
    $("#pcActiveText").textContent = detail ? `${name}: ${detail} · ${TEXT.pc_active}` : `${name} · ${TEXT.pc_active}`;
  }
}
let pollTimer=0, sseActive=false;
function startPolling() { if (pollTimer) return; refresh(); pollTimer=setInterval(() => { if (token) refresh(); }, 3000); }
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer=0; } }
async function startLive() {
  if (!token) return;
  // SSE keeps the phone in step with the PC in real time; polling is the fallback
  // for browsers without fetch streaming, or whenever the stream drops.
  if (!window.ReadableStream || !window.TextDecoder) { startPolling(); return; }
  try {
    const response = await fetch("/events", {headers:{"Authorization":"Bearer " + token}});
    if (response.status === 401) { token=""; localStorage.removeItem("lumable_session"); show(false); return; }
    if (!response.ok || !response.body) throw new Error("no stream");
    stopPolling(); sseActive=true;
    const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer="";
    for (;;) {
      const {value, done}=await reader.read(); if (done) break;
      buffer += decoder.decode(value, {stream:true}); let split;
      while ((split=buffer.indexOf("\\n\\n")) >= 0) {
        const frame=buffer.slice(0, split); buffer=buffer.slice(split + 2);
        for (const line of frame.split("\\n")) if (line.startsWith("data:")) { try { applyState(JSON.parse(line.slice(5).trim())); } catch (_) {} }
      }
    }
  } catch (_) {}
  sseActive=false;
  startPolling();
  setTimeout(() => { if (token && !sseActive) { stopPolling(); startLive(); } }, 5000);
}
const SWATCHES=[[255,255,255],[255,60,0],[255,170,0],[0,200,120],[0,150,255],[120,60,255],[255,0,140],[20,20,20]];
const MODES=["chill","gaming","night","rainbow"];
const PC_MODES=["screen","music","effect","diy"];
function build() {
  $("#swatches").innerHTML=SWATCHES.map(c=>`<button class="sw" data-rgb="${c.join(',')}" style="background:rgb(${c[0]},${c[1]},${c[2]})" onclick="setColor(${c[0]},${c[1]},${c[2]})"></button>`).join("");
  $("#modes").innerHTML=MODES.map(mode=>`<button data-mode="${mode}" onclick="quick('${mode}')">${TEXT['mode_'+mode]}</button>`).join("");
  $("#pcModes").innerHTML=PC_MODES.map(mode=>`<button data-pc="${mode}" onclick="pcMode('${mode}')">${TEXT['pc_'+mode]}</button>`).join("");
}
text(); build(); installPicker(); installScenes(); renderRecent(); paintColour(255,255,255,true); show(!!token); if (token) { startLive(); loadScenes(); }
</script>
</body>
</html>
"""


def build_mobile_page(labels: Mapping[str, str] | None = None, *, language: str = "en") -> str:
    """Render the static remote with the desktop application's current language."""
    text = dict(_FALLBACK_LABELS)
    if labels:
        text.update({key: str(value) for key, value in labels.items()})
    safe_text = json.dumps(text, ensure_ascii=False).replace("</", "<\\/")
    safe_language = "".join(char for char in language.lower() if char.isalpha() or char == "-") or "en"
    return _TEMPLATE.replace("__TEXT__", safe_text).replace("__LANG__", safe_language)


MOBILE_PAGE = build_mobile_page()
