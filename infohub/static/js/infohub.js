// Click a screenshot to view it full size; click again or press Esc to close.
document.addEventListener("click", function (event) {
    var link = event.target.closest("a.zoomable");
    if (!link) return;
    event.preventDefault();

    var overlay = document.createElement("div");
    overlay.className = "lightbox";
    var img = document.createElement("img");
    img.src = link.href;
    img.alt = link.dataset.caption || "";
    overlay.appendChild(img);
    if (link.dataset.caption) {
        var caption = document.createElement("p");
        caption.textContent = link.dataset.caption;
        overlay.appendChild(caption);
    }

    function close() {
        overlay.remove();
        document.removeEventListener("keydown", onKey);
    }
    function onKey(e) {
        if (e.key === "Escape") close();
    }
    overlay.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(overlay);
});

// „Помогна ли ви?“ under a guide: send the answer without leaving the page. The server remembers
// it per account, so the question isn't shown again (the page still works without JavaScript).
// „Не“ first asks what was missing; it is sent only with at least a few words.
(function () {
    var box = document.querySelector("[data-feedback]");
    if (!box) return;
    var form = box.querySelector("form");
    if (!form) return;
    var ask = form.querySelector(".feedback__ask");
    var why = form.querySelector(".feedback__reason");
    var reason = form.querySelector("textarea[name=reason]");
    var error = form.querySelector("[data-feedback-error]");
    var MIN_LENGTH = 5;  // stats.views.REASON_MIN_LENGTH
    var NEEDED = error.textContent;

    function show(asking) {
        ask.hidden = asking;
        why.hidden = !asking;
        error.hidden = true;
        if (asking) reason.focus();
    }
    function done(sent) {
        form.hidden = true;
        box.querySelector(sent ? "[data-feedback-sent]" : "[data-feedback-thanks]").hidden = false;
    }
    function fail(message) {
        error.textContent = message;
        error.hidden = false;
        reason.focus();
    }

    form.querySelector("[data-feedback-no]").addEventListener("click", function (event) {
        event.preventDefault();
        show(true);
    });
    form.querySelector("[data-feedback-cancel]").addEventListener("click", function (event) {
        event.preventDefault();
        show(false);
    });

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        var helpful = event.submitter ? event.submitter.value : "yes";
        var data = new FormData(form);
        data.append("helpful", helpful);
        var headers = { "X-Requested-With": "XMLHttpRequest" };
        if (helpful === "yes") {
            data.delete("reason");
            fetch(form.action, { method: "POST", body: data, headers: headers });
            done(false);
            return;
        }
        if (reason.value.trim().length < MIN_LENGTH) {
            fail(NEEDED);
            return;
        }
        fetch(form.action, { method: "POST", body: data, headers: headers }).then(function (response) {
            if (response.ok) return done(true);
            return response.json().then(function (answer) { fail(answer.error); });
        }).catch(function () {
            fail("Отговорът не можа да се изпрати. Проверете връзката и опитайте пак.");
        });
    });
})();

// A PDF in a post is also shown inside the page, where the browser can do that (computers). Phones
// can't show a PDF in a page (Android: nothing, iPhone: first page only), so there only the button stays.
(function () {
    var wide = window.matchMedia && window.matchMedia("(min-width: 700px)").matches;
    if (!navigator.pdfViewerEnabled || !wide) return;
    document.querySelectorAll("[data-pdf-view]").forEach(function (box) {
        var frame = document.createElement("iframe");
        frame.src = box.dataset.pdfView + "#view=FitH";
        frame.title = box.dataset.title || "PDF";
        frame.loading = "lazy";
        box.appendChild(frame);
        box.hidden = false;
    });
})();
