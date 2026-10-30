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
(function () {
    var box = document.querySelector("[data-feedback]");
    if (!box) return;
    var form = box.querySelector("form");
    var thanks = box.querySelector(".feedback__thanks");

    function done() {
        if (form) form.hidden = true;
        thanks.hidden = false;
    }
    if (!form) return;

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        var data = new FormData(form);
        data.append("helpful", event.submitter ? event.submitter.value : "yes");
        fetch(form.action, { method: "POST", body: data, headers: { "X-Requested-With": "XMLHttpRequest" } });
        done();
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
