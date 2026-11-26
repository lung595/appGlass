/* appGlass for any WebKitGTK app: injected at document end (top frame) by appglass-wk.so
   (APPGLASS_JS), next to webkit-glass.css (APPGLASS_CSS, a USER stylesheet with the levels).
   It reads the page's own colours and marks elements; the stylesheet does the painting:
     html[data-agl-root]   the page colour (html, else body, else what covers the window)
                           at the content level; --agl-root holds it
     [data-agl=clear]      an opaque element of the page colour: transparent (the glass shows)
     [data-agl=bar]        a large opaque element of another colour (a sidebar, a toolbar,
                           a card): that colour at the bar level; --agl-c holds it
     [data-agl-under]      what an opaque full-window overlay covers (a setup step laid over
                           the app): hidden while the overlay, now glass, stays
   Never touched: text, images, small elements (buttons, fields), translucent backgrounds and
   popups (dialog, menu, listbox, tooltip, popover, a floating box with a shadow), which stay
   opaque. A MutationObserver re-marks what the page adds or restyles; a theme change
   (prefers-color-scheme, a class or data-* on html/body) marks everything again. */
(function () {
  "use strict";
  if (window.top !== window || window.__aglGlass) return;
  window.__aglGlass = 1;
  var d = document.documentElement;
  var POPUP = "dialog,[role=dialog],[role=alertdialog],[role=menu],[role=listbox],[role=tooltip]," +
    "[role=combobox][aria-expanded=true]+*,[popover],[aria-modal=true]";
  var TOL = 6, MIN_SIDE = 40, MIN_AREA = 0.015, MIN_STRIP = 16;
  var root = null, queue = [], all = true, timer = 0, obs = null, sig = "";

  function parse(s) {
    var m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,\/]\s*([\d.]+)(%?))?\s*\)$/.exec(s);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4] / (m[5] ? 100 : 1)];
    m = /^color\(srgb\s+([\d.e-]+)\s+([\d.e-]+)\s+([\d.e-]+)(?:\s*\/\s*([\d.]+)(%?))?\s*\)$/.exec(s);
    if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : +m[4] / (m[5] ? 100 : 1)];
    return null;
  }
  function solid(c) { return c && c[3] > 0.98; }
  function same(a, b) {
    return Math.abs(a[0] - b[0]) <= TOL && Math.abs(a[1] - b[1]) <= TOL && Math.abs(a[2] - b[2]) <= TOL;
  }
  function str(c) { return Math.round(c[0]) + ", " + Math.round(c[1]) + ", " + Math.round(c[2]); }
  function bg(el) { return parse(getComputedStyle(el).backgroundColor); }
  function unmark(el) {
    if (el.hasAttribute("data-agl")) { el.removeAttribute("data-agl"); el.style.removeProperty("--agl-c"); }
  }

  // the page colour: html, else body, else the element under the middle of the window
  // that covers it, else the canvas (dark when the text is light)
  function findRoot() {
    d.removeAttribute("data-agl-root");
    var c = bg(d);
    if (!solid(c) && document.body) c = bg(document.body);
    if (!solid(c)) {
      var vw = innerWidth, vh = innerHeight;
      var el = document.elementFromPoint(vw / 2, vh / 2);
      for (; el && el !== d && el !== document.body; el = el.parentElement) {
        var r = el.getBoundingClientRect(), x = bg(el);
        if (solid(x) && r.width >= vw * 0.9 && r.height >= vh * 0.9) { c = x; break; }
      }
    }
    if (!solid(c)) {
      var t = parse(getComputedStyle(document.body || d).color) || [0, 0, 0, 1];
      c = (t[0] + t[1] + t[2]) / 3 > 128 ? [30, 30, 30, 1] : [255, 255, 255, 1];
    }
    return c;
  }

  // what covers the window is a page (an app shell, a full-window setup step), never a popup
  function popup(el, cs, r) {
    if (r.width >= innerWidth * 0.9 && r.height >= innerHeight * 0.9) return false;
    if (el.matches(POPUP)) return true;
    var p = cs.position;
    if (p !== "fixed" && p !== "absolute") return false;
    return cs.boxShadow !== "none" || (cs.zIndex !== "auto" && +cs.zIndex > 0);
  }

  // a bar: a large box (a sidebar, a card), or a strip along most of the window (a status bar)
  function large(r) {
    if (r.width >= MIN_SIDE && r.height >= MIN_SIDE && r.width * r.height >= innerWidth * innerHeight * MIN_AREA) return true;
    return Math.min(r.width, r.height) >= MIN_STRIP &&
      (r.width >= innerWidth * 0.5 || r.height >= innerHeight * 0.5);
  }

  function inPopup(el) {
    for (var p = el.parentElement; p && p !== d; p = p.parentElement) {
      if (p.hasAttribute("data-agl-pop")) return true;
    }
    return false;
  }

  // one element: returns false when it (and so its subtree) is a popup
  function mark(el) {
    if (el === d) return true;
    unmark(el);
    var cs = getComputedStyle(el);
    if (cs.display === "none") return false;
    var r = el.getBoundingClientRect();
    if (popup(el, cs, r)) { el.setAttribute("data-agl-pop", ""); return false; }
    el.removeAttribute("data-agl-pop");
    var c = parse(cs.backgroundColor);
    if (!solid(c) || cs.backgroundImage !== "none") return true;
    if (same(c, root)) {
      if (el === document.body || (r.width >= MIN_SIDE && r.height >= MIN_SIDE)) el.setAttribute("data-agl", "clear");
    } else if (large(r)) {
      el.style.setProperty("--agl-c", str(c));
      el.setAttribute("data-agl", "bar");
    }
    if (el.hasAttribute("data-agl") && el !== document.body && (cs.position === "fixed" || cs.position === "absolute") &&
        r.width >= innerWidth * 0.9 && r.height >= innerHeight * 0.9) cover(el, cs);
    return true;
  }

  // an opaque page laid over the window (a setup step): once it is glass, what it covered
  // would show through it, so that is hidden while it stays
  function cover(el, cs) {
    el.setAttribute("data-agl-cover", "");
    var z = cs.zIndex === "auto" ? 0 : +cs.zIndex;
    for (var n = el; n && n !== document.body && n !== d; n = n.parentElement) {
      var before = true;
      for (var s = n.parentElement ? n.parentElement.firstElementChild : null; s; s = s.nextElementSibling) {
        if (s === n) { before = false; continue; }
        if (/^(SCRIPT|STYLE|LINK|TEMPLATE)$/.test(s.tagName)) continue;
        var sc = getComputedStyle(s), sz = sc.zIndex, pos = sc.position !== "static";
        if (!pos || (sz === "auto" ? before : +sz < z)) s.setAttribute("data-agl-under", "");
      }
    }
  }

  function gone(el) {
    if (!el.getClientRects().length) return true;
    var cs = getComputedStyle(el);
    return cs.visibility === "hidden" || cs.display === "none";
  }

  function walk(el) {
    if (!mark(el)) return;
    for (var k = el.firstElementChild; k; k = k.nextElementSibling) walk(k);
  }

  function themeSig() {
    var b = document.body;
    var cls = function (e) { return e ? (e.getAttribute("class") || "").replace(/\bagl-inactive\b/, "") : ""; };
    var data = function (e) {
      if (!e) return "";
      var s = "";
      for (var i = 0; i < e.attributes.length; i++) {
        var a = e.attributes[i];
        if (/^data-/.test(a.name) && !/^data-agl/.test(a.name)) s += a.name + "=" + a.value + ";";
      }
      return s;
    };
    return cls(d) + "|" + data(d) + "|" + cls(b) + "|" + data(b) + "|" + (d.getAttribute("style") || "").replace(/--agl-root:[^;]*;?/, "");
  }

  function run() {
    timer = 0;
    if (obs) queue = queue.concat(obs.takeRecords());
    var s = themeSig();
    if (s !== sig) { sig = s; all = true; }
    // a cover no longer shown (a class on an ancestor hid it, a parent went display:none):
    // what it hid comes back with a full run
    if (!all && Array.prototype.some.call(document.querySelectorAll("[data-agl-cover]"), gone)) all = true;
    if (all) {
      all = false; queue = [];
      Array.prototype.forEach.call(document.querySelectorAll("[data-agl]"), unmark);
      Array.prototype.forEach.call(document.querySelectorAll("[data-agl-cover],[data-agl-under]"), function (e) {
        e.removeAttribute("data-agl-cover"); e.removeAttribute("data-agl-under");
      });
      d.setAttribute("data-agl-still", "");   // findRoot shows the page's own colour for a moment
      root = findRoot();
      d.style.setProperty("--agl-root", str(root));
      d.setAttribute("data-agl-root", "");
      getComputedStyle(d).backgroundColor;   // settled without a fade, then the fade is back
      d.removeAttribute("data-agl-still");
      if (document.body) walk(document.body);
    } else {
      var todo = [];
      queue.forEach(function (m) {
        if (m.type === "attributes") todo.push(m.target);
        else for (var i = 0; i < m.addedNodes.length; i++) if (m.addedNodes[i].nodeType === 1) todo.push(m.addedNodes[i]);
      });
      queue = [];
      todo.forEach(function (el) {
        if (!el.isConnected || el === d || inPopup(el)) return;
        if (el.parentElement && el.parentElement !== d && !document.body.contains(el)) return;
        walk(el);
      });
    }
    sig = themeSig();
    if (obs) obs.takeRecords();   // our own changes
  }

  function later(full) {
    if (full) all = true;
    if (!timer) timer = setTimeout(run, 80);
  }

  obs = new MutationObserver(function (ms) {
    for (var i = 0; i < ms.length; i++) {
      var m = ms[i];
      if (m.type === "attributes" && /^data-agl/.test(m.attributeName)) continue;
      if (m.type === "attributes" && m.target === d && m.attributeName === "class" &&
          (m.oldValue || "").replace(/\s*\bagl-inactive\b/, "") === (d.getAttribute("class") || "").replace(/\s*\bagl-inactive\b/, "")) continue;
      if (m.type === "attributes" && m.target.hasAttribute("data-agl-cover")) { all = true; continue; }
      for (var j = 0; j < m.removedNodes.length; j++) {
        var x = m.removedNodes[j];
        if (x.nodeType === 1 && (x.hasAttribute("data-agl-cover") || x.querySelector("[data-agl-cover]"))) all = true;
      }
      queue.push(m);
    }
    if (all) { later(true); return; }
    if (queue.length) later(false);
  });
  obs.observe(d, { subtree: true, childList: true, attributes: true, attributeOldValue: true,
                   attributeFilter: ["class", "style", "hidden", "open", "data-theme"] });
  try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { later(true); }); } catch (e) {}
  addEventListener("resize", function () { later(true); });
  addEventListener("load", function () { later(true); });
  run();
})();
