// The post editor (Quill + editor.js) and the „Кой да я вижда“ picker (audience.js) in jsdom, on the
// editor pages rendered by tests/test_js.py. Usage: node editor.test.js <static folder> <pages folder>
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const STATIC = path.resolve(process.argv[2]);
const PAGES = path.resolve(process.argv[3]);
const quillSrc = fs.readFileSync(path.join(STATIC, "vendor/quill/quill.js"), "utf8");
const editorSrc = fs.readFileSync(path.join(STATIC, "js/editor.js"), "utf8");
const audienceSrc = fs.readFileSync(path.join(STATIC, "js/audience.js"), "utf8");
let passed = 0, failed = [];
function check(name, ok, detail) {
    if (ok) { passed++; console.log("OK   " + name); }
    else { failed.push(name); console.log("FAIL " + name + (detail !== undefined ? "  -> " + JSON.stringify(detail) : "")); }
}

function load(file) {
    const html = fs.readFileSync(path.join(PAGES, file), "utf8").replace(/<script src=[^>]*><\/script>/g, "");
    const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://testserver/manage/" });
    const w = dom.window;
    w.Element.prototype.scrollIntoView = function () {};
    w.document.getSelection = w.document.getSelection || (() => w.getSelection());
    const sent = [];
    w.XMLHttpRequest = class {
        constructor() { this.upload = { listeners: {}, addEventListener: (n, f) => { this.upload.listeners[n] = f; } }; this.listeners = {}; this.headers = {}; }
        open(method, url) { this.method = method; this.url = url; }
        setRequestHeader(k, v) { this.headers[k] = v; }
        addEventListener(n, f) { this.listeners[n] = f; }
        getResponseHeader() { return "application/json"; }
        send(data) { this.data = data; sent.push(this); }
        respond(status, body) {
            this.status = status; this.responseText = JSON.stringify(body);
            if (this.upload.listeners.progress) this.upload.listeners.progress({ lengthComputable: true, loaded: 10, total: 10 });
            this.listeners.load();
        }
    };
    w.confirmAnswer = true;
    w.confirm = () => w.confirmAnswer;
    w.eval(quillSrc);
    w.eval(editorSrc);
    w.eval(audienceSrc);
    return { w, d: w.document, sent };
}
const blocksOf = (d) => [...d.querySelectorAll("[data-blocks] > .eblock")];
const labels = (d) => blocksOf(d).map((b) => b.querySelector(".eblock__label").textContent);
function submit(w, d) {
    const form = d.querySelector("form.post-form");
    const event = new w.Event("submit", { cancelable: true });
    form.dispatchEvent(event);
    return { prevented: event.defaultPrevented, body: JSON.parse(form.querySelector("input[name=body]").value || "null") };
}
function file(w, name, type, size) { return new w.File(["x".repeat(size || 10)], name, { type }); }
function fileEvent(w, type, files, prop) {
    const e = new w.Event(type, { bubbles: true, cancelable: true });
    const list = { files, types: ["Files"], getData: () => "" };
    Object.defineProperty(e, prop, { value: list });
    return e;
}

// ---------- edit page with every block type ----------
{
    const { w, d, sent } = load("edit.html");
    check("edit: 9 blocks rendered", blocksOf(d).length === 9, blocksOf(d).length);
    check("edit: step numbers restart after a heading",
        JSON.stringify(labels(d)) === JSON.stringify(["Стъпка 1", "Стъпка 2", "Подзаглавие", "Стъпка 1", "Текст", "Снимка", "Видео", "Бележка", "Файл за изтегляне"]), labels(d));
    const first = blocksOf(d)[0];
    check("edit: step title filled", first.querySelector("input.eblock__title").value === "Стъпка А");
    check("edit: step has 2 picture tiles", first.querySelectorAll(".epic img").length === 2);
    check("edit: Quill toolbar created with Bulgarian titles", first.querySelector(".ql-toolbar .ql-bold") && first.querySelector(".ql-bold").title.startsWith("Удебелен"));
    check("edit: rich text loaded into Quill", first.querySelector(".ql-editor strong") && first.querySelector(".ql-editor strong").textContent === "удебелен");
    check("edit: first block ↑ disabled, last ↓ disabled", first.querySelectorAll(".eblock__tool")[0].disabled && blocksOf(d)[8].querySelectorAll(".eblock__tool")[1].disabled);
    check("edit: video name shown", blocksOf(d)[6].querySelector(".edoc__info strong").textContent.endsWith(".mp4"));
    check("edit: note style selected + coloured", blocksOf(d)[7].querySelector("select").value === "tip" && blocksOf(d)[7].dataset.style === "tip");
    check("edit: empty hint hidden", d.querySelector("[data-empty]").hidden === true);

    let { prevented, body } = submit(w, d);
    check("edit: submit not blocked", !prevented);
    check("edit: 9 blocks serialized in order", body.map((b) => b.type).join() === "step,step,heading,step,text,image,video,note,file", body.map((b) => b.type));
    check("edit: step html keeps bold + list", /<strong>удебелен<\/strong>/.test(body[0].html) && /<ol><li>едно<\/li><\/ol>/.test(body[0].html), body[0].html);
    check("edit: step pictures keep ids", body[0].images.length === 2 && body[0].images.every((i) => Number.isInteger(i.id)));
    check("edit: empty Quill gives empty html", body[1].html === "");
    check("edit: text keeps italic, link, bullets", /<em>текст<\/em>/.test(body[4].html) && /href="https:\/\/example.com"/.test(body[4].html) && /<ul><li>т1<\/li><\/ul>/.test(body[4].html), body[4].html);
    check("edit: image/video/file ids + captions", body[5].image.id && body[5].caption === "Надпис" && body[6].document.id && body[6].caption === "Видео" && body[8].document.id && body[8].title === "Изтегли");
    check("edit: note style tip", body[7].style === "tip" && /Съвет!/.test(body[7].html));

    // move the heading up: steps 1,2 become separate around it
    blocksOf(d)[2].querySelectorAll(".eblock__tool")[0].click();
    check("move: heading up -> numbering updated", JSON.stringify(labels(d).slice(0, 4)) === JSON.stringify(["Стъпка 1", "Подзаглавие", "Стъпка 1", "Стъпка 2"]), labels(d));
    // picture order within a step
    const tiles = () => [...blocksOf(d)[0].querySelectorAll(".epic")].map((t) => t._item.id);
    const before = tiles();
    blocksOf(d)[0].querySelectorAll(".epic")[1].querySelector("button").click(); // ← on the 2nd picture
    check("pictures: ← swaps order", JSON.stringify(tiles()) === JSON.stringify([before[1], before[0]]), tiles());
    blocksOf(d)[0].querySelector(".epic .epic__remove").click();
    check("pictures: ✕ removes one", tiles().length === 1);

    // remove: non-empty asks; "no" keeps it
    w.confirmAnswer = false;
    blocksOf(d)[1].querySelectorAll(".eblock__tool")[2].click();
    check("remove: refused confirm keeps block", blocksOf(d).length === 9);
    w.confirmAnswer = true;
    blocksOf(d)[1].querySelectorAll(".eblock__tool")[2].click();
    check("remove: confirmed removes block", blocksOf(d).length === 8);

    // add under the active block
    blocksOf(d)[0].querySelector("input.eblock__title").dispatchEvent(new w.FocusEvent("focusin", { bubbles: true }));
    d.querySelector("[data-add=note]").click();
    check("add: new block goes under the active block", blocksOf(d)[1].classList.contains("eblock--note"), labels(d));
    d.querySelector("[data-add=heading]").click();
    check("add: second click goes under the active block again", blocksOf(d)[2].classList.contains("eblock--heading") || blocksOf(d)[1].classList.contains("eblock--heading"), labels(d));
    check("no uploads happened yet", sent.length === 0);
}

// ---------- new post: uploads, paste, drop ----------
{
    const { w, d, sent } = load("new.html");
    check("new: empty hint visible", d.querySelector("[data-empty]").hidden === false && blocksOf(d).length === 0);
    d.querySelector("[data-add=step]").click();
    const step = blocksOf(d)[0];
    check("new: step added and title focused", step && d.activeElement === step.querySelector("input.eblock__title"));
    check("new: empty hint hidden after add", d.querySelector("[data-empty]").hidden === true);

    // choose 2 pictures with the file input
    const input = step.querySelector(".epics-field input[type=file]");
    Object.defineProperty(input, "files", { value: [file(w, "a.png", "image/png"), file(w, "b.jpg", "image/jpeg")], configurable: true });
    input.dispatchEvent(new w.Event("change"));
    check("upload: 2 requests sent as kind=image with place + csrf", sent.length === 2 && sent[0].data.get("kind") === "image" && sent[0].data.get("place") !== null && sent[0].data.get("csrfmiddlewaretoken"));
    check("upload: placeholders with progress shown", step.querySelectorAll(".epic--loading").length === 2);
    const button = d.querySelector("[data-submit]");
    check("upload: submit disabled while uploading", button.disabled === true && /Качване/.test(d.querySelector("[data-status]").textContent));
    let res = submit(w, d);
    check("upload: submit blocked while uploading", res.prevented);
    sent[0].respond(200, { item: { id: 11, title: "a", thumb: "/media/images/a.png" }, warning: "" });
    sent[1].respond(400, { error: "„b.jpg“ не е снимка или е повреден файл." });
    check("upload: success tile + failure message", step.querySelectorAll(".epic img").length === 1 && /не е снимка/.test(step.querySelector(".eblock__messages").textContent));
    check("upload: submit enabled again", button.disabled === false);

    // too big video refused in the browser, no request
    d.querySelector("[data-add=video]").click();
    const videoBlock = blocksOf(d)[1];
    const vInput = videoBlock.querySelector("input[type=file]");
    Object.defineProperty(vInput, "files", { value: [new w.File([new Uint8Array(10)], "big.mp4", { type: "video/mp4" })], configurable: true });
    Object.defineProperty(vInput.files[0], "size", { value: 400 * 1048576 });
    vInput.dispatchEvent(new w.Event("change"));
    check("video: over the limit refused before upload", sent.length === 2 && /максимумът е 300 MB/.test(videoBlock.textContent));
    Object.defineProperty(vInput, "files", { value: [file(w, "ok.mov", "video/quicktime")], configurable: true });
    vInput.dispatchEvent(new w.Event("change"));
    check("video: upload sent as kind=video", sent.length === 3 && sent[2].data.get("kind") === "video");
    sent[2].respond(200, { item: { id: 21, title: "ok", name: "ok.mov", size: 2048 }, warning: "Видеото „ok.mov“ може да не тръгне във всеки браузър." });
    check("video: name + warning shown", /ok\.mov/.test(videoBlock.querySelector(".edoc__info").textContent) && videoBlock.querySelector(".eblock__warning"));

    // paste a screenshot into the step title -> step pictures
    step.querySelector("input.eblock__title").value = "Направете снимка";
    step.querySelector("input.eblock__title").dispatchEvent(fileEvent(w, "paste", [file(w, "image.png", "image/png")], "clipboardData"));
    check("paste: screenshot in step goes to its pictures", sent.length === 4 && step.querySelectorAll(".epic--loading").length === 1);
    sent[3].respond(200, { item: { id: 12, title: "s", thumb: "/media/images/s.png" }, warning: "" });

    // paste into the text editor of the step (Quill uploader)
    const qlEditor = step.querySelector(".ql-editor");
    qlEditor.dispatchEvent(fileEvent(w, "paste", [file(w, "image.png", "image/png")], "clipboardData"));
    check("paste: screenshot into step text also goes to its pictures", sent.length === 5 && sent[4].data.get("kind") === "image", sent.length);
    if (sent[4]) sent[4].respond(200, { item: { id: 13, title: "t", thumb: "/media/images/t.png" }, warning: "" });

    // paste a screenshot into a text block -> new picture block below it
    d.querySelector("[data-add=text]").click();
    const textBlock = blocksOf(d).find((b) => b.classList.contains("eblock--text"));
    textBlock.querySelector(".ql-editor").dispatchEvent(fileEvent(w, "paste", [file(w, "image.png", "image/png")], "clipboardData"));
    const afterText = textBlock.nextElementSibling;
    check("paste: into text -> new picture block under it", afterText && afterText.classList.contains("eblock--image"), labels(d));
    sent[sent.length - 1].respond(200, { item: { id: 14, title: "u", thumb: "/media/images/u.png" }, warning: "" });

    // drop a PDF and a video next to the blocks -> new blocks
    const n = blocksOf(d).length;
    d.querySelector("[data-editor]").dispatchEvent(fileEvent(w, "drop", [file(w, "Правилник.pdf", "application/pdf"), file(w, "clip.mp4", "video/mp4")], "dataTransfer"));
    const after = textBlock.nextElementSibling, after2 = after.nextElementSibling;
    check("drop: PDF -> file block, MP4 -> video block, under the active block", blocksOf(d).length === n + 2 && after.classList.contains("eblock--file") && after2.classList.contains("eblock--video"), labels(d));
    sent.slice(-2).forEach((x, i) => x.respond(200, { item: { id: 30 + i, title: "f", name: "f", size: 10 }, warning: "" }));

    // type into the step text through Quill's API
    const quill = w.Quill.find(step.querySelector(".ql-container"));
    quill.insertText(0, "Натиснете ");
    quill.insertText(10, "Старт", { bold: true });
    res = submit(w, d);
    const s0 = res.body[0];
    check("serialize: step title, html, 3 pictures in order", s0.title === "Направете снимка" && /Натиснете(\s|&nbsp;)*<strong>Старт<\/strong>/.test(s0.html) && s0.images.map((i) => i.id).join() === "11,12,13", s0);
    check("serialize: video with id 21", res.body.some((b) => b.type === "video" && b.document && b.document.id === 21));
    check("serialize: picture block with id 14", res.body.some((b) => b.type === "image" && b.image && b.image.id === 14));
    check("submit: button shows 'Запазване…'", d.querySelector("[data-submit]").textContent === "Запазване…");
}


// ---------- what can go wrong: upload answers, expired token, Back after a failed save ----------
{
    const { w, d, sent } = load("new.html");
    d.querySelector("[data-add=image]").click();
    const block = blocksOf(d)[0];
    const pick = (name) => {
        const input = block.querySelector("input[type=file]");
        Object.defineProperty(input, "files", { value: [file(w, name, "image/png")], configurable: true });
        input.dispatchEvent(new w.Event("change"));
    };
    const messagesOf = () => block.querySelector(".eblock__messages").textContent;
    pick("big.png");
    sent[sent.length - 1].respond(413, null);
    check("upload 413 (server limit): says the file is too big for the server", /по-голям, отколкото сървърът приема/.test(messagesOf()), messagesOf());
    pick("crash.png");
    sent[sent.length - 1].respond(500, null);
    check("upload 500: says it's a server error and what to do", /Грешка на сървъра.*crash\.png.*администратора/.test(messagesOf()), messagesOf());
    pick("out.png");
    sent[sent.length - 1].respond(302, null);
    check("upload answered by the login page: says to log in again", /влезте пак в нов таб/.test(messagesOf()), messagesOf());

    d.cookie = "csrftoken=NEWTOKEN123";
    pick("after-login.png");
    check("upload sends the current token from the cookie", sent[sent.length - 1].data.get("csrfmiddlewaretoken") === "NEWTOKEN123");
    sent[sent.length - 1].respond(200, { item: { id: 5, title: "p", thumb: "/media/images/p.png" }, warning: "" });

    const form = d.querySelector("form.post-form");
    const button = d.querySelector("[data-submit]");
    const ev = new w.Event("submit", { cancelable: true });
    form.dispatchEvent(ev);
    check("save sends the current token from the cookie", !ev.defaultPrevented && form.querySelector("input[name=csrfmiddlewaretoken]").value === "NEWTOKEN123");
    check("save: button shows „Запазване…“ and is disabled", button.disabled && button.textContent === "Запазване…");
    const back = new w.Event("pageshow");
    Object.defineProperty(back, "persisted", { value: true });
    w.dispatchEvent(back);
    check("Back to the page after a failed save: the button works again", !button.disabled && button.textContent === "Публикувай");
}

// ---------- „Кой да я вижда“ (audience.js) ----------
{
    const rowOf = (d, name) => [...d.querySelectorAll("[data-venue-row]")].find((r) => r.textContent.includes(name));
    const staffOf = (d, name) => rowOf(d, name).querySelector("[data-staff]");
    const managerOf = (d, name) => rowOf(d, name).querySelector("[data-manager]");
    const summaryOf = (d) => d.querySelector("[data-audience-summary]").textContent;
    const change = (w, el) => el.dispatchEvent(new w.Event("change", { bubbles: true }));
    const tick = (w, el, on) => { el.checked = on; change(w, el); };
    const posted = (w, d, name) => new w.FormData(d.querySelector("form.post-form")).getAll(name);
    const sendForm = (w, d) => {
        const ev = new w.Event("submit", { cancelable: true });
        d.querySelector("form.post-form").dispatchEvent(ev);
        return ev;
    };

    let { w, d } = load("new.html");
    const all = d.querySelector("[data-all-venues]");
    const pick = d.querySelector("[data-audience-pick]");
    const text = d.body.textContent;
    check("audience: new post – „Всички обекти“ ticked, table hidden", all.checked && pick.hidden && /всички обекти/.test(summaryOf(d)), summaryOf(d));
    check("audience: no „Управителите на всички обекти“, clear text for „all“, title placeholder",
        !text.includes("Управителите на всички обекти") && text.includes("също и на обекти, добавени по-късно") && !text.includes("(и на новите)")
        && d.querySelector("input[name=title]").placeholder === "Задайте кратко и информативно заглавие");
    check("audience: two columns per venue, incl. training", !!staffOf(d, "Перник") && !!managerOf(d, "София – Младост") && !!rowOf(d, "Обучение"));

    tick(w, all, false);
    check("audience: untick all -> table shown, warning", !pick.hidden && summaryOf(d) === "Още не сте избрали кой да я вижда.");
    check("audience: nobody chosen -> submit stopped before the editor", sendForm(w, d).defaultPrevented && d.querySelector("[data-submit]").textContent !== "Запазване…");

    tick(w, staffOf(d, "Перник"), true);
    check("audience: staff ticked -> its manager shown ticked + greyed", managerOf(d, "Перник").checked && managerOf(d, "Перник").disabled);
    check("audience: staff ticked -> the manager column is greyed for the others (no mixing)",
        managerOf(d, "Младост").disabled && !managerOf(d, "Младост").checked && d.querySelector("[data-column=manager]").disabled && !d.querySelector("[data-column=staff]").disabled);
    tick(w, staffOf(d, "Младост"), true);
    check("audience: staff summary", summaryOf(d) === "Ще се вижда от: служителите и управителите на Перник, София – Младост.", summaryOf(d));
    check("audience: posted = staff only (implied managers not sent)", posted(w, d, "staff_venues").length === 2 && posted(w, d, "manager_venues").length === 0,
        [posted(w, d, "staff_venues"), posted(w, d, "manager_venues")]);
    tick(w, staffOf(d, "Обучение"), true);
    tick(w, staffOf(d, "Младост"), false);
    check("audience: untick one of several staff -> its manager tick goes, nothing locks (user's bug)",
        !managerOf(d, "Младост").checked && !staffOf(d, "Младост").disabled && !staffOf(d, "Перник").disabled && !staffOf(d, "Обучение").disabled
        && managerOf(d, "Младост").disabled && managerOf(d, "Перник").checked && managerOf(d, "Обучение").checked
        && summaryOf(d) === "Ще се вижда от: служителите и управителите на Обучение, Перник.", summaryOf(d));
    tick(w, staffOf(d, "Младост"), true);
    check("audience: and it can be ticked again", staffOf(d, "Младост").checked && managerOf(d, "Младост").checked
        && posted(w, d, "staff_venues").length === 3 && posted(w, d, "manager_venues").length === 0);
    tick(w, staffOf(d, "Обучение"), false);
    tick(w, staffOf(d, "Младост"), false);
    tick(w, staffOf(d, "Перник"), false);
    check("audience: staff unticked -> manager column free again, nothing ticked",
        !managerOf(d, "Перник").checked && !managerOf(d, "Перник").disabled && !managerOf(d, "Младост").disabled && !d.querySelector("[data-column=manager]").disabled);

    tick(w, managerOf(d, "Младост"), true);
    check("audience: manager ticked -> the staff column is greyed (no mixing)",
        staffOf(d, "Перник").disabled && staffOf(d, "Младост").disabled && d.querySelector("[data-column=staff]").disabled && !managerOf(d, "Перник").disabled);
    tick(w, managerOf(d, "Перник"), true);
    check("audience: managers summary", summaryOf(d) === "Ще се вижда от: само управителите на Перник, София – Младост.", summaryOf(d));
    check("audience: posted = managers only", posted(w, d, "manager_venues").length === 2 && posted(w, d, "staff_venues").length === 0);
    d.querySelector("[data-column=manager]").click();
    check("audience: „всички“ for managers ticks every venue (= all managers)", [...d.querySelectorAll("[data-manager]")].every((b) => b.checked)
        && d.querySelector("[data-audience-count]").textContent === "Избрани: 3");
    d.querySelector("[data-column=manager]").click();
    check("audience: and again clears them; staff column free again", [...d.querySelectorAll("[data-manager]")].every((b) => !b.checked) && !staffOf(d, "Перник").disabled);

    const search = d.querySelector("[data-audience-search]");
    search.value = "млад"; search.dispatchEvent(new w.Event("input"));
    check("audience: search shows only matching venues", !rowOf(d, "Младост").hidden && rowOf(d, "Перник").hidden && rowOf(d, "Обучение").hidden);
    d.querySelector("[data-column=staff]").click();
    check("audience: „всички“ ticks only the shown venues", staffOf(d, "Младост").checked && !staffOf(d, "Обучение").checked && !staffOf(d, "Перник").checked);
    search.value = ""; search.dispatchEvent(new w.Event("input"));
    const key = new w.KeyboardEvent("keydown", { key: "Enter", cancelable: true });
    search.dispatchEvent(key);
    check("audience: Enter in the search box doesn't send the form", key.defaultPrevented);

    ({ w, d } = load("edit.html"));
    check("audience: edit page restores the post's choice",
        !d.querySelector("[data-all-venues]").checked && !d.querySelector("[data-audience-pick]").hidden
        && managerOf(d, "Младост").checked && !managerOf(d, "Перник").checked && staffOf(d, "Перник").disabled
        && summaryOf(d) === "Ще се вижда от: само управителите на София – Младост.", summaryOf(d));
    const ev = sendForm(w, d);
    check("audience: valid choice -> the editor sends the form", !ev.defaultPrevented && d.querySelector("[data-submit]").textContent === "Запазване…");
}

// ---------- „Запази като чернова“ next to „Публикувай“ ----------
{
    let { w, d } = load("new.html");
    const publish = d.querySelector("[data-submit]");
    const draft = d.querySelector("button[name=action][value=draft]");
    check("draft: new post has both buttons", publish && draft && publish.textContent.trim() === "Публикувай" && draft.textContent.trim() === "Запази като чернова");
    const form = d.querySelector("form.post-form");
    const ev = new w.SubmitEvent("submit", { cancelable: true, submitter: draft });
    form.dispatchEvent(ev);
    const action = form.querySelector("input[type=hidden][name=action]");
    check("draft: the pressed button's choice is sent in a hidden field", action && action.value === "draft");
    check("draft: both buttons disabled, the pressed one shows „Запазване…“", publish.disabled && draft.disabled
        && draft.textContent === "Запазване…" && publish.textContent.trim() === "Публикувай");
    const back = new w.Event("pageshow"); Object.defineProperty(back, "persisted", { value: true });
    w.dispatchEvent(back);
    check("draft: Back brings both buttons back", !publish.disabled && !draft.disabled && draft.textContent.trim() === "Запази като чернова");
    const ev2 = new w.SubmitEvent("submit", { cancelable: true, submitter: publish });
    form.dispatchEvent(ev2);
    check("draft: then „Публикувай“ replaces the choice (one field)", form.querySelectorAll("input[name=action][type=hidden]").length === 1
        && form.querySelector("input[type=hidden][name=action]").value === "publish");
}

console.log(`\n${passed}/${passed + failed.length} passed`);
if (failed.length) { console.log("FAILED:", failed); process.exit(1); }
