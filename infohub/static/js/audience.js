/* „Кой да я вижда“ in the post editor: all venues, or chosen venues in one of two columns:
   their staff (the venue's manager sees it too: shown ticked and greyed) or only their manager.
   Never both columns at once: ticking one column greys out the other. Without JavaScript the
   checkboxes still work; the server checks the choice (guides/audience.py). */
(function () {
    "use strict";

    var box = document.querySelector("[data-audience]");
    if (!box) return;
    var form = box.closest("form");
    var all = box.querySelector("[data-all-venues]");
    var pick = box.querySelector("[data-audience-pick]");
    var search = box.querySelector("[data-audience-search]");
    var count = box.querySelector("[data-audience-count]");
    var summary = box.querySelector("[data-audience-summary]");
    var rows = Array.prototype.slice.call(box.querySelectorAll("[data-venue-row]"));
    var columnButtons = Array.prototype.slice.call(box.querySelectorAll("[data-column]"));

    function nameOf(row) { return row.querySelector("[data-venue-name]").textContent.trim(); }
    function staffBox(row) { return row.querySelector("[data-staff]"); }
    function managerBox(row) { return row.querySelector("[data-manager]"); }

    function list(names) {
        return names.length > 6 ? names.length + " обекта" : names.join(", ");
    }

    function refresh() {
        pick.hidden = all.checked;
        // A ticked staff box shows its manager as ticked ("implied", disabled so it isn't sent).
        // Unticking the staff removes that tick again, before anything counts it as a manager choice.
        rows.forEach(function (row) {
            var m = managerBox(row);
            if (staffBox(row).checked) {
                m.checked = true;
                m.dataset.implied = "1";
            } else if (m.dataset.implied) {
                m.checked = false;
                delete m.dataset.implied;
            }
        });
        var staff = rows.filter(function (row) { return staffBox(row).checked; });
        var managers = rows.filter(function (row) { return !staffBox(row).checked && managerBox(row).checked; });
        var staffMode = staff.length > 0, managerMode = managers.length > 0;
        rows.forEach(function (row) {
            staffBox(row).disabled = managerMode;
            managerBox(row).disabled = staffMode;  // in staff mode: implied ticks or the other column
        });
        columnButtons.forEach(function (button) {
            button.disabled = button.dataset.column === "staff" ? managerMode : staffMode;
        });

        var text, empty = false;
        if (all.checked) {
            text = "Ще се вижда от: всички обекти (служители и управители).";
        } else if (staffMode) {
            text = "Ще се вижда от: служителите и управителите на " + list(staff.map(nameOf)) + ".";
        } else if (managerMode) {
            text = "Ще се вижда от: само управителите на " + list(managers.map(nameOf)) + ".";
        } else {
            text = "Още не сте избрали кой да я вижда.";
            empty = true;
        }
        summary.textContent = text;
        summary.classList.toggle("is-empty", empty);
        var chosen = staff.length + managers.length;
        if (count) count.textContent = chosen ? "Избрани: " + chosen : "";
    }

    function filter() {
        var q = (search.value || "").trim().toLowerCase();
        rows.forEach(function (row) { row.hidden = q && row.dataset.name.indexOf(q) === -1; });
    }

    box.addEventListener("change", refresh);

    // „всички“ in a column ticks every shown venue; if all of them are ticked already it clears them.
    columnButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            var get = button.dataset.column === "staff" ? staffBox : managerBox;
            var boxes = rows.filter(function (row) { return !row.hidden; }).map(get).filter(function (b) { return !b.disabled; });
            var on = boxes.some(function (b) { return !b.checked; });
            boxes.forEach(function (b) { b.checked = on; });
            refresh();
            form.dispatchEvent(new Event("change"));  // the editor then asks before leaving unsaved
        });
    });

    if (search) search.addEventListener("input", filter);
    // Enter in the search box must not send the form.
    if (search) search.addEventListener("keydown", function (e) { if (e.key === "Enter") e.preventDefault(); });

    // Before the editor's own submit handler: nobody chosen = stay on the page and show it.
    document.addEventListener("submit", function (e) {
        if (e.target !== form) return;
        refresh();
        if (summary.classList.contains("is-empty")) {
            e.preventDefault();
            e.stopImmediatePropagation();
            box.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }, true);

    refresh();
}());
