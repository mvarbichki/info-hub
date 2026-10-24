// dashboard.js on the Потребители page (rendered by tests/test_js.py): fields per role and the
// suggested login name. Usage: node users.test.js <static folder> <pages folder>
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const src = fs.readFileSync(path.resolve(process.argv[2], "js/dashboard.js"), "utf8");
let passed = 0, failed = [];
function check(name, ok, detail) {
    if (ok) { passed++; console.log("OK   " + name); }
    else { failed.push(name); console.log("FAIL " + name + (detail !== undefined ? "  -> " + JSON.stringify(detail) : "")); }
}
function load(file) {
    const html = fs.readFileSync(path.join(path.resolve(process.argv[3]), file), "utf8").replace(/<script src=[^>]*><\/script>/g, "");
    const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://testserver/manage/users/" });
    dom.window.eval(src);
    return dom.window;
}
function change(w, el, value) { el.value = value; el.dispatchEvent(new w.Event("change")); }
const visible = (el) => !el.hidden;

let w = load("users.html"), d = w.document;
const role = d.querySelector("[data-role]"), venue = d.querySelector("[data-venue]"), name = d.querySelector("[data-username]");
const venueField = d.querySelector("label[data-for-venue]"), deptField = d.querySelector("label[data-for-editor]");
const opt = (label) => [...venue.options].find((o) => o.textContent.startsWith(label)).value;
check("default role editor: department shown, venue hidden, no name", role.value === "editor" && visible(deptField) && !visible(venueField) && name.value === "", role.value);
change(w, role, "staff");
check("staff: venue shown, department hidden", visible(venueField) && !visible(deptField));
check("no venue yet: no suggestion", name.value === "");
change(w, venue, opt("Перник"));
check("Перник + staff -> pernik_staff2 (pernik_staff taken)", name.value === "pernik_staff2", name.value);
change(w, role, "manager");
check("role manager -> pernik_manager2 (pernik_manager taken)", name.value === "pernik_manager2", name.value);
change(w, venue, opt("София – Цариградско шосе"));
check("Цариградско шосе -> carigradsko_manager", name.value === "carigradsko_manager", name.value);
name.value = "carigradsko_shef";
change(w, role, "staff");
check("own name kept when the role changes", name.value === "carigradsko_shef");
name.value = "";
change(w, venue, opt("Перник"));
check("cleared name -> suggestion again", name.value === "pernik_staff2", name.value);
change(w, role, "editor");
check("back to editor: suggestion removed, placeholder for editors", name.value === "" && name.placeholder.includes("finance") && visible(deptField) && !visible(venueField));
check("password help per role", visible(d.querySelector("span[data-for-editor]")) && !visible(d.querySelector("span[data-for-venue]")));

w = load("users_new.html"); d = w.document;
check("„+ Добави потребител“: staff + Перник preselected and suggested", d.querySelector("[data-role]").value === "staff" && d.querySelector("[data-username]").value === "pernik_staff2", d.querySelector("[data-username]").value);

w = load("users_error.html"); d = w.document;
check("after an error the chosen role stays (editor) with its fields", d.querySelector("[data-role]").value === "editor" && visible(d.querySelector("label[data-for-editor]")) && d.body.innerHTML.includes("Изберете раздел"));

console.log(`\n${passed}/${passed + failed.length} passed`);
if (failed.length) process.exit(1);
