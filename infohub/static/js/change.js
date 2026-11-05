/* „Важна промяна“ in the post editor: the note and „Искай ново потвърждение“ show only when the box
   is ticked, the latter only while the post asks for „Прочетох“. Without JavaScript everything is
   shown; the server ignores a new confirmation on a post that doesn't ask for one. */
(function () {
    "use strict";

    var box = document.querySelector("[data-change]");
    if (!box) return;
    var form = box.closest("form");
    var important = box.querySelector("[data-important]");
    var more = box.querySelector("[data-important-more]");
    var reconfirm = box.querySelector("[data-reconfirm]");
    var needsAck = form.querySelector("input[name=needs_ack]");

    // A hidden part is also disabled, so it isn't sent (a note typed before unticking is kept on the page).
    function show(part, on) {
        part.hidden = !on;
        Array.prototype.forEach.call(part.querySelectorAll("input"), function (input) { input.disabled = !on; });
    }

    function refresh() {
        show(more, important.checked);
        if (important.checked) show(reconfirm, !!(needsAck && needsAck.checked));
    }

    form.addEventListener("change", refresh);  // also after the editor restores an autosaved copy
    refresh();
}());
