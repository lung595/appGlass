"""webkit-glass.js, run under node against a tiny fake DOM: an element restyled
several times between two runs is re-marked once, not once per record."""

import json
import os
import shutil
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(REPO, "shims", "webkit-shim", "webkit-glass.js")

# a fake DOM just deep enough for the script: body > bar > item; getComputedStyle
# counts its calls per element, the observer callback and the timer are kept to fire by hand
HARNESS = r"""
const vm = require("vm"), fs = require("fs");
class El {
  constructor(tag, kids) {
    this.tagName = tag; this.attrs = {}; this.kids = kids || []; this.parentElement = null;
    this.isConnected = true; this.nodeType = 1;
    this.kids.forEach(k => k.parentElement = this);
    const self = this;
    this.style = { setProperty(n, v) { self.attrs.style = n + ":" + v + ";"; }, removeProperty() {} };
  }
  get firstElementChild() { return this.kids[0] || null; }
  get nextElementSibling() {
    const s = this.parentElement ? this.parentElement.kids : [];
    return s[s.indexOf(this) + 1] || null;
  }
  get attributes() { return Object.keys(this.attrs).map(n => ({ name: n, value: this.attrs[n] })); }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  removeAttribute(n) { delete this.attrs[n]; }
  hasAttribute(n) { return n in this.attrs; }
  matches() { return false; }
  contains(e) { for (; e; e = e.parentElement) if (e === this) return true; return false; }
  querySelector() { return null; }
  getClientRects() { return [1]; }
  getBoundingClientRect() { return { width: 300, height: 600 }; }
}
const item = new El("DIV"), bar = new El("DIV", [item]), body = new El("BODY", [bar]);
const html = new El("HTML", [body]);
const calls = new Map();
let observed = null, timer = null;
const document = { documentElement: html, body, querySelectorAll: () => [], elementFromPoint: () => body };
const ctx = {
  document, innerWidth: 1000, innerHeight: 800,
  getComputedStyle(el) {
    calls.set(el, (calls.get(el) || 0) + 1);
    const c = el === html || el === body ? "rgb(255, 255, 255)" : "rgb(40, 40, 40)";
    return { backgroundColor: c, backgroundImage: "none", display: "block", position: "static",
             boxShadow: "none", zIndex: "auto", color: "rgb(0, 0, 0)", visibility: "visible" };
  },
  MutationObserver: class { constructor(f) { observed = f; } observe() {} takeRecords() { return []; } },
  matchMedia: () => ({ addEventListener() {} }),
  addEventListener() {},
  setTimeout(f) { timer = f; return 1; },
};
ctx.window = ctx; ctx.top = ctx;
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
calls.clear();
const rec = { type: "attributes", target: bar, attributeName: "style", oldValue: "", removedNodes: [] };
observed([rec, rec, rec, rec, rec]);
timer();
console.log(JSON.stringify({ bar: calls.get(bar) || 0, item: calls.get(item) || 0 }));
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class Incremental(unittest.TestCase):
    def test_five_records_on_one_element_mark_its_subtree_once(self):
        out = subprocess.run(["node", "-e", HARNESS, JS], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout), {"bar": 1, "item": 1})


if __name__ == "__main__":
    unittest.main()
