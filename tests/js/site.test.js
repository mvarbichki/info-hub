// infohub.js on a post with a PDF and an Excel file (rendered by tests/test_js.py): the PDF is shown
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
function load(pdfViewer, width) {
    const html = fs.readFileSync(path.join(path.resolve(process.argv[3]), "guide.html"), "utf8").replace(/<script src=[^>]*><\/script>/g, "");
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
check("frame opens the PDF fitted to the width", frame && frame.src.endsWith(".pdf#view=FitH") && frame.src.includes("/media/documents/"), frame && frame.src);
check("frame has the button text as title", frame && frame.title === "Правилник за работа", frame && frame.title);
check("frame loads lazily", frame && frame.loading === "lazy");
check("download button still there", d.querySelectorAll("a.file-link").length === 2);

d = load(true, 390);
check("phone width: no frame, box hidden", !d.querySelector("[data-pdf-view] iframe") && d.querySelector("[data-pdf-view]").hidden);
d = load(false, 1280);
check("browser without a PDF viewer: no frame", !d.querySelector("[data-pdf-view] iframe"));
d = load(undefined, 1280);
check("older browser (no pdfViewerEnabled): no frame", !d.querySelector("[data-pdf-view] iframe"));

console.log(failed.length ? `${failed.length} FAILED of ${passed + failed.length}` : `${passed}/${passed} passed`);
process.exit(failed.length ? 1 : 0);
