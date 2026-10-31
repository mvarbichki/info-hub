// infohub.js on the login page (rendered by tests/test_js.py): „Покажи“ and the Caps Lock warning.
// Usage: node login.test.js <static folder> <pages folder>
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const src = fs.readFileSync(path.resolve(process.argv[2], "js/infohub.js"), "utf8");
const html = fs.readFileSync(path.join(path.resolve(process.argv[3]), "login.html"), "utf8").replace(/<script src=[^>]*><\/script>/g, "");
let passed = 0, failed = [];
function check(name, ok, detail) {
    if (ok) { passed++; console.log("OK   " + name); }
    else { failed.push(name); console.log("FAIL " + name + (detail !== undefined ? "  -> " + JSON.stringify(detail) : "")); }
}

const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://testserver/login/" });
const w = dom.window, d = w.document;
w.eval(src);
const field = d.getElementById("id_password"), toggle = d.querySelector("[data-password-toggle]"), caps = d.querySelector("[data-caps-warning]");

check("the button is shown by the script", !toggle.hidden);
check("hidden password at first", field.type === "password" && toggle.textContent === "Покажи" && toggle.getAttribute("aria-pressed") === "false");
toggle.click();
check("„Покажи“ shows it", field.type === "text" && toggle.textContent === "Скрий" && toggle.getAttribute("aria-pressed") === "true");
check("the cursor stays in the field", d.activeElement === field);
toggle.click();
check("„Скрий“ hides it again", field.type === "password" && toggle.textContent === "Покажи");

function key(type, capsOn) {
    const e = new w.KeyboardEvent(type, { key: "a", bubbles: true });
    e.getModifierState = (name) => name === "CapsLock" && capsOn;
    field.dispatchEvent(e);
}
check("no Caps Lock warning at first", caps.hidden);
key("keydown", true);
check("Caps Lock on: warning", !caps.hidden);
key("keyup", false);
check("Caps Lock off: warning gone", caps.hidden);
key("keydown", true);
field.dispatchEvent(new w.Event("blur"));
check("leaving the field hides the warning", caps.hidden);

toggle.click();
field.form.dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
check("sent as a password field (password managers)", field.type === "password" && toggle.textContent === "Покажи");

console.log(failed.length ? `${failed.length} FAILED of ${passed + failed.length}` : `${passed}/${passed} passed`);
process.exit(failed.length ? 1 : 0);
