.pragma library

// The search over the settings: every word typed must start a word of the
// entry's label, keywords or help (AND, case and accents folded). A word in
// the label counts most, then the keywords, then the help; a whole word a
// little more than a prefix. Pure: no state, tested in search.test.qml.
//
// An entry is {id, category, label, help, keywords: []}; a result is
// {id, category, score}, best first (ties keep the index order).

var MAX_WORDS = 6;
var MAX_QUERY = 64;
var WEIGHT = {
    "label": 3,
    "keywords": 2,
    "help": 1
};

function words(text) {
    return String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().split(/[^a-z0-9]+/).filter(function (w) {
        return w.length > 0;
    });
}

function _score(fields, word) {
    var best = 0;
    for (var f in fields) {
        var list = fields[f];
        for (var i = 0; i < list.length; i++) {
            if (list[i].indexOf(word) !== 0)
                continue;
            var s = WEIGHT[f] + (list[i] === word ? 0.5 : 0);
            if (s > best)
                best = s;
        }
    }
    return best;
}

function search(entries, query) {
    var qw = words(String(query || "").slice(0, MAX_QUERY)).slice(0, MAX_WORDS);
    if (!qw.length)
        return [];
    var out = [];
    var list = Array.isArray(entries) ? entries : [];
    for (var i = 0; i < list.length; i++) {
        var e = list[i];
        if (!e || !e.id)
            continue;
        var fields = {
            "label": words(e.label),
            "keywords": words((e.keywords || []).join(" ")),
            "help": words(e.help)
        };
        var total = 0;
        for (var j = 0; j < qw.length; j++) {
            var s = _score(fields, qw[j]);
            if (!s) {
                total = 0;
                break;
            }
            total += s;
        }
        if (total > 0)
            out.push({
                "id": e.id,
                "category": e.category,
                "score": total,
                "at": i
            });
    }
    out.sort(function (a, b) {
        return (b.score - a.score) || (a.at - b.at);
    });
    return out.map(function (r) {
        return {
            "id": r.id,
            "category": r.category,
            "score": r.score
        };
    });
}
