// infohub.js on a post with a PDF and an Excel file (rendered by tests/test_js.py): „Помогна ли ви?“ and the PDF shown
// inside the page on computers, not on phones. Usage: node site.test.js <static folder> <pages folder>
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const src = fs.readFileSync(path.resolve(process.argv[2], "js/infohub.js"), "utf8");
let passed = 0, failed = [];
function check(name, ok, detail) {
    if (ok) { passed++; console.log("OK   " + name); }
    else { failed.push(name); console.log("FAIL " + name + (detail !== undefined ? "  -> " + JSON.stringify(detail) : "")); }
}
function load(pdfViewer, width, change) {
    let html = fs.readFileSync(path.join(path.resolve(process.argv[3]), "guide.html"), "utf8").replace(/<script src=[^>]*><\/script>/g, "");
    if (change) html = change(html);
    const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://testserver/" });
    const w = dom.window;
    if (pdfViewer !== undefined) Object.defineProperty(w.navigator, "pdfViewerEnabled", { value: pdfViewer });
    w.matchMedia = (query) => ({ matches: width >= parseInt(query.match(/\d+/)[0], 10) });
    w.eval(src);
    return w.document;
}

let d = load(true, 1280);
const boxes = d.querySelectorAll("[data-pdf-view]");
check("one PDF box in the page (none for Excel)", boxes.length === 1, boxes.length);
const frame = boxes[0].querySelector("iframe");
check("computer: the PDF is shown in the page", frame && !boxes[0].hidden);
check("frame opens the PDF fitted to the width, without the viewer's toolbar", frame && frame.src.endsWith(".pdf#toolbar=0&view=FitH") && frame.src.includes("/media/documents/"), frame && frame.src);
check("frame has the button text as title", frame && frame.title === "Правилник за работа", frame && frame.title);
check("frame loads lazily", frame && frame.loading === "lazy");
check("download button still there", d.querySelectorAll("a.file-link").length === 2);

d = load(true, 390);
check("phone width: no frame, box hidden", !d.querySelector("[data-pdf-view] iframe") && d.querySelector("[data-pdf-view]").hidden);
d = load(false, 1280);
check("browser without a PDF viewer: no frame", !d.querySelector("[data-pdf-view] iframe"));
d = load(undefined, 1280);
check("older browser (no pdfViewerEnabled): no frame", !d.querySelector("[data-pdf-view] iframe"));

// „Помогна ли ви?“: „Не“ asks for a reason first and is sent only with one.
function feedbackPage(answer) {
    const html = fs.readFileSync(path.join(path.resolve(process.argv[3]), "guide.html"), "utf8").replace(/<script src=[^>]*><\/script>/g, "");
    const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://testserver/" });
    const w = dom.window;
    w.sent = [];
    w.fetch = (url, options) => {
        w.sent.push(Object.fromEntries(options.body.entries()));
        return Promise.resolve({ ok: answer.ok, json: () => Promise.resolve(answer.json || {}) });
    };
    w.matchMedia = () => ({ matches: false });
    w.eval(src);
    return w;
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
// Pressing a submit button (jsdom's requestSubmit doesn't pass the button on).
function press(w, button) {
    button.form.dispatchEvent(new w.SubmitEvent("submit", { cancelable: true, submitter: button }));
}

(async () => {
    let w = feedbackPage({ ok: true }), f = w.document;
    const ask = f.querySelector(".feedback__ask"), why = f.querySelector(".feedback__reason");
    const error = f.querySelector("[data-feedback-error]"), text = f.querySelector("textarea[name=reason]");
    const send = why.querySelector("button[value=no]");
    check("at first: the question, no reason box", !ask.hidden && why.hidden);
    f.querySelector("[data-feedback-no]").click();
    await tick();
    check("„Не“: reason box opens, nothing sent", ask.hidden && !why.hidden && w.sent.length === 0);
    check("reason box gets the focus", f.activeElement === text);
    press(w, send);
    await tick();
    check("empty reason: not sent, message shown", w.sent.length === 0 && !error.hidden && error.textContent.includes("не се изпраща"));
    text.value = "  лош ";
    press(w, send);
    await tick();
    check("too short: not sent", w.sent.length === 0);
    f.querySelector("[data-feedback-cancel]").click();
    check("„Отказ“: back to the question", !ask.hidden && why.hidden && error.hidden);
    f.querySelector("[data-feedback-no]").click();
    text.value = "Няма снимка на бланката";
    press(w, send);
    await tick(); await tick();
    check("with a reason: sent as „Не“ + reason", w.sent.length === 1 && w.sent[0].helpful === "no" && w.sent[0].reason === "Няма снимка на бланката", w.sent);
    check("then the thank-you with the department", f.querySelector(".feedback__form").hidden && !f.querySelector("[data-feedback-sent]").hidden
        && f.querySelector("[data-feedback-sent]").textContent.includes("изпратена"));

    w = feedbackPage({ ok: false, json: { error: "Сървърът каза не." } }); f = w.document;
    f.querySelector("[data-feedback-no]").click();
    f.querySelector("textarea[name=reason]").value = "Няма снимка";
    press(w, f.querySelector(".feedback__reason button[value=no]"));
    await tick(); await tick();
    check("refused by the server: its message, form stays", !f.querySelector(".feedback__form").hidden
        && f.querySelector("[data-feedback-error]").textContent === "Сървърът каза не.");

    w = feedbackPage({ ok: true }); f = w.document;
    press(w, f.querySelector(".feedback__ask button[value=yes]"));
    await tick();
    check("„Да“: sent at once, without a reason", w.sent.length === 1 && w.sent[0].helpful === "yes" && !("reason" in w.sent[0]), w.sent);
    check("„Да“: thank-you shown", f.querySelector(".feedback__form").hidden && !f.querySelector("[data-feedback-thanks]").hidden);

    // A form is sent once: a second click does nothing (and asks nothing) until the page comes back.
    d = load(true, 1280);
    d.body.insertAdjacentHTML("beforeend", '<form method="post" id="once"><button>Изтрий</button></form>'
        + '<form method="get" id="find"><button>Търси</button></form>'
        + '<form method="post" id="own"><button>Прати</button></form>');
    const once = d.getElementById("once"), find = d.getElementById("find"), own = d.getElementById("own");
    let asked = 0;
    once.addEventListener("submit", () => { asked++; });  // like dashboard.js's confirm dialog
    own.addEventListener("submit", (e) => e.preventDefault());  // like „Помогна ли ви?“
    const submitOnce = (form) => { const e = new d.defaultView.Event("submit", { bubbles: true, cancelable: true }); form.dispatchEvent(e); return e.defaultPrevented; };
    check("first submit goes through", submitOnce(once) === false && once.hasAttribute("data-sending"));
    check("second submit is stopped, no second dialog", submitOnce(once) === true && asked === 1, asked);
    check("a search form (GET) isn't held", submitOnce(find) === false && submitOnce(find) === false && !find.hasAttribute("data-sending"));
    check("a form its own script sends isn't held", submitOnce(own) === true && !own.hasAttribute("data-sending") && submitOnce(own) === true);
    d.defaultView.dispatchEvent(new d.defaultView.Event("pageshow"));
    check("back on the page: the form works again", !once.hasAttribute("data-sending") && submitOnce(once) === false && asked === 2);

    console.log(failed.length ? `${failed.length} FAILED of ${passed + failed.length}` : `${passed}/${passed} passed`);
process.exit(failed.length ? 1 : 0);
})();
