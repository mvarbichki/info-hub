// Management panel: ask before deleting (or other actions marked with data-confirm).
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
});

// Потребители → „Нов потребител“: show the venue or the department for the chosen role, and
// suggest the login name (pernik_staff, pernik_staff2 … when taken) until the user types their own.
(function () {
    var form = document.querySelector("[data-user-form]");
    if (!form) return;
    var role = form.querySelector("[data-role]");
    var venue = form.querySelector("[data-venue]");
    var name = form.querySelector("[data-username]");
    var bases = JSON.parse(document.getElementById("login-bases").textContent);
    var taken = JSON.parse(document.getElementById("taken-usernames").textContent);
    var suggested = "";

    function suggestion() {
        if (role.value === "editor" || !bases[venue.value]) return "";
        var base = bases[venue.value] + "_" + role.value, candidate = base, n = 2;
        while (taken.indexOf(candidate) !== -1) { candidate = base + n; n += 1; }
        return candidate;
    }

    function update() {
        var editor = role.value === "editor";
        form.querySelectorAll("[data-for-venue]").forEach(function (el) { el.hidden = editor; });
        form.querySelectorAll("[data-for-editor]").forEach(function (el) { el.hidden = !editor; });
        name.placeholder = editor ? "напр. finance" : "избира се от обекта и ролята";
        if (name.value === "" || name.value === suggested) {
            suggested = suggestion();
            name.value = suggested;
        }
    }

    role.addEventListener("change", update);
    venue.addEventListener("change", update);
    update();
})();
