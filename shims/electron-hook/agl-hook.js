// agl-hook.js: appGlass main-process hook for any Electron app.
// Load it in the MAIN process before (or after) the app creates windows:
//   - loader:        require('/path/agl-hook.js') from a resources/app/ shim, then require the app's real main
//   - NODE_OPTIONS:  NODE_OPTIONS="--require /path/agl-hook.js" (only if the fuse allows it AND exe is named "electron")
//   - inspector:     Runtime.evaluate `require('/path/agl-hook.js')` over --inspect
// Env: AGL_CSS=<css file> (re-read on every page load, so a DMS/matugen rewrite applies on reload)
//      AGL_MATCH=<regex on page URL> (default: all), AGL_LOG=1
'use strict';
const fs = require('fs');
let electron;
try { electron = require('electron'); } catch (e) { }
function log(...a) { if (process.env.AGL_LOG) console.error('[appglass]', ...a); if (process.env.AGL_MARK) try { fs.appendFileSync(process.env.AGL_MARK, process.pid + ' ' + a.join(' ') + '\n'); } catch (e) {} }
log('loaded', process.type, process.argv0);
// NODE_OPTIONS route: drop our own --require so children (VS Code terminal, extension host, helpers) do not inherit it
if (process.env.NODE_OPTIONS && /agl-hook\.js/.test(process.env.NODE_OPTIONS)) {
  const rest = process.env.NODE_OPTIONS.replace(/--require[= ]?\S*agl-hook\.js\S*/g, '').trim();
  if (rest) process.env.NODE_OPTIONS = rest; else delete process.env.NODE_OPTIONS;
}

function install() {
  if (global.__aglInstalled) return; global.__aglInstalled = true;
  const { app, BrowserWindow, webContents } = electron;
  const CLEAR = '#00000000';
  const match = process.env.AGL_MATCH ? new RegExp(process.env.AGL_MATCH) : null;
  const cssFile = process.env.AGL_CSS || '';
  const readCss = () => { try { return fs.readFileSync(process.env.AGL_CSS || '', 'utf8'); } catch (e) { return ''; } };
  // 1) every later setBackgroundColor on a glass window stays clear (Discord, VS Code re-set it on theme change)
  const proto = Object.getPrototypeOf(BrowserWindow.prototype).setBackgroundColor ? Object.getPrototypeOf(BrowserWindow.prototype) : BrowserWindow.prototype;
  const orig = proto.setBackgroundColor;
  proto.setBackgroundColor = function (c) { return orig.call(this, this.__agl ? CLEAR : c); };
  const keys = new WeakMap();
  function css(wc) {
    const url = wc.getURL();
    if (match && !match.test(url)) return;
    const c = readCss(); if (!c) return;
    const old = keys.get(wc);
    if (old) wc.removeInsertedCSS(old).catch(() => {});
    wc.insertCSS(c, { cssOrigin: 'user' }).then(k => { keys.set(wc, k); log('css', url, c.length); }).catch(e => log('css err', e));
  }
  function glass(w) {
    if (w.__agl) return; w.__agl = true;
    const clear = (why) => { try { w.setBackgroundColor(CLEAR); orig.call(w, CLEAR); log('clear', why, w.id, w.getBackgroundColor()); } catch (e) { log('clear err', e); } };
    clear('created');
    w.once('ready-to-show', () => clear('ready-to-show')); w.once('show', () => clear('show'));
    w.webContents.once('did-finish-load', () => clear('did-finish-load'));
    const wc = w.webContents;
    wc.on('dom-ready', () => css(wc));
    if (!wc.isLoading() && wc.getURL()) css(wc);
    // AGL_NOMENU=1: drop the native (GTK, always opaque) menubar of this window; app keyboard shortcuts in the
    // renderer keep working, menu-only accelerators are lost. autoHideMenuBar alone did NOT hide it (Signal).
    if (process.env.AGL_NOMENU) { const nm = () => { try { w.removeMenu(); } catch (e) {} }; nm(); w.once('show', nm); wc.once('did-finish-load', nm); }
    setTimeout(() => { try { log('bg after 5s', w.id, w.getBackgroundColor(), 'menu', w.isMenuBarVisible && w.isMenuBarVisible()); } catch (e) {} }, 5000);
    log('glass window', w.id, w.getTitle());
  }
  if (process.env.AGL_NOMENU && electron.Menu) {  // apps re-set the application menu later (Linux applies it per window)
    const sam = electron.Menu.setApplicationMenu.bind(electron.Menu);
    electron.Menu.setApplicationMenu = (m) => { sam(m); BrowserWindow.getAllWindows().forEach(w => { if (w.__agl) try { w.removeMenu(); } catch (e) {} }); };
  }
  app.on('browser-window-created', (_e, w) => glass(w));
  if (app.isReady()) BrowserWindow.getAllWindows().forEach(glass);
  global.__aglGlass = glass;
  global.__aglRecss = () => BrowserWindow.getAllWindows().forEach(w => css(w.webContents));
  log('installed');
}
function tryInstall(n) {
  try { electron = require('electron'); } catch (e) { }
  if (electron && electron.app && electron.BrowserWindow) return install();
  if (n < 200) setTimeout(() => tryInstall(n + 1), n ? 5 : 0); else log('no electron.app');
}
if (process.type === 'browser' || (!process.type && electron && electron.app)) tryInstall(0);
module.exports = { install };
