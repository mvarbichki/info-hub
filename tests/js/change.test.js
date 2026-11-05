// change.js in the post editor (rendered by tests/test_js.py): „Важна промяна“ shows its note and
// „Искай ново потвърждение“ only when they apply, and a hidden part isn't sent.
// Usage: node change.test.js <static folder> <pages folder>
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const src = fs.readFileSync(path.resolve(process.argv[2], "js/change.js"), "utf8");
const pages = path.resolve(process.argv[3]);
let passed = 0, failed = [];
function check(name, ok, detail) {
    if (ok) { passed++; console.log("OK   " + name); }
    else { failed.push(name); console.log("FAIL " + name + (detail !== undefined ? "  -> " + JSON.stringify(detail) : "")); }
}
function load(name) {
    const html = fs.readFileSync(path.join(pages, name), "utf8").replace(/<script src=[^>]*><\/script>/g, "");
    const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://testserver/manage/1/" });
    dom.window.eval(src);
    return dom.window;
}
function sent(form, w) { return Array.from(new w.FormData(form).keys()); }

let w = load("change.html"), d = w.document;
const form = d.querySelector(".post-form");
const important = d.querySelector("[data-important]"), more = d.querySelector("[data-important-more]");
const reconfirm = d.querySelector("[data-reconfirm]"), needsAck = d.querySelector("input[name=needs_ack]");
const note = d.querySelector("input[name=change_note]");

check("unticked: note hidden and not sent", more.hidden && !sent(form, w).includes("change_note"));
important.checked = true; important.dispatchEvent(new w.Event("change", { bubbles: true }));
check("ticked: the note shows", !more.hidden && sent(form, w).includes("change_note"));
check("no „Прочетох“ asked: no new confirmation offered", reconfirm.hidden && !sent(form, w).includes("reconfirm"));
needsAck.checked = true; needsAck.dispatchEvent(new w.Event("change", { bubbles: true }));
d.querySelector("input[name=reconfirm]").checked = true;
check("„Прочетох“ asked: new confirmation offered", !reconfirm.hidden && sent(form, w).includes("reconfirm"));
needsAck.checked = false; needsAck.dispatchEvent(new w.Event("change", { bubbles: true }));
check("„Прочетох“ switched off: hidden again and not sent", reconfirm.hidden && !sent(form, w).includes("reconfirm"));
note.value = "Нов телефон";
important.checked = false; important.dispatchEvent(new w.Event("change", { bubbles: true }));
check("unticked again: the typed note stays on the page but isn't sent", more.hidden && note.value === "Нов телефон" && !sent(form, w).includes("change_note"));

w = load("change_waiting.html"); d = w.document;
check("a waiting change opens ticked with its note", d.querySelector("[data-important]").checked && !d.querySelector("[data-important-more]").hidden
    && d.querySelector("input[name=change_note]").value === "Чака");

console.log(failed.length ? `${failed.length} FAILED of ${passed + failed.length}` : `${passed}/${passed} passed`);
process.exit(failed.length ? 1 : 0);
