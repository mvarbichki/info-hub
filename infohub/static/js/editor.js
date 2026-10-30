// Post editor (/manage/new/ and /manage/<id>/). A post is a list of blocks: step, text, heading,
// picture, video, note and file. Text is edited with Quill. Pictures, videos and files are uploaded
// as soon as they are chosen (with progress); the form only sends their ids (see guides/editor.py).
(function () {
    "use strict";
    var root = document.querySelector("[data-editor]");
    if (!root || !window.Quill) return;

    var config = JSON.parse(document.getElementById("editor-config").textContent);
    var form = root.closest("form");
    var list = root.querySelector("[data-blocks]");
    var empty = root.querySelector("[data-empty]");
    var output = form.querySelector("input[name=body]");
    // „Публикувай“ and „Запази като чернова“ (their name "action" says which one was pressed).
    var buttons = Array.prototype.slice.call(form.querySelectorAll("button[type=submit]"));
    var labels = buttons.map(function (button) { return button.textContent; });
    var status = form.querySelector("[data-status]");
    var statusText = status.textContent;
    var place = form.querySelector("select[name=place]");
    var csrfField = form.querySelector("input[name=csrfmiddlewaretoken]");
    var MB = 1048576;

    // The current CSRF token: logging in again (e.g. in another tab) replaces it, and the copy
    // in the page would then be refused. The cookie always has the valid one.
    function csrf() {
        var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : csrfField.value;
    }
    var pending = 0, dirty = false, submitting = false, activeBlock = null;

    function setButtons(disabled) {
        buttons.forEach(function (button, i) {
            button.disabled = disabled;
            button.textContent = labels[i];
        });
    }

    var LABELS = {
        step: "Стъпка", text: "Текст", heading: "Подзаглавие", image: "Снимка",
        video: "Видео", note: "Бележка", file: "Файл за изтегляне"
    };
    var NOTE_STYLES = [["info", "Информация"], ["tip", "Съвет"], ["warning", "Внимание"]];
    var TOOLBAR = [["bold", "italic"], [{ list: "ordered" }, { list: "bullet" }], ["link"], ["clean"]];
    var TOOL_TITLES = {
        ".ql-bold": "Удебелен (Ctrl+B)", ".ql-italic": "Курсив (Ctrl+I)",
        ".ql-list[value=ordered]": "Номериран списък", ".ql-list[value=bullet]": "Списък с точки",
        ".ql-link": "Връзка към сайт", ".ql-clean": "Махни форматирането"
    };
    var IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"];

    // --- helpers -------------------------------------------------------------------

    function h(tag, props, children) {
        var node = document.createElement(tag);
        Object.keys(props || {}).forEach(function (key) {
            var value = props[key];
            if (key === "text") node.textContent = value;
            else if (key === "class") node.className = value;
            else if (key.indexOf("on") === 0) node.addEventListener(key.slice(2), value);
            else if (value !== false && value !== undefined) node.setAttribute(key, value === true ? "" : value);
        });
        (children || []).forEach(function (child) { if (child) node.appendChild(child); });
        return node;
    }

    function changed() { dirty = true; }

    function formatMb(bytes) {
        if (bytes < MB) return Math.max(1, Math.round(bytes / 1024)) + " KB";  // not „0.0 MB“ for a small PDF
        return (bytes / MB).toFixed(bytes < 10 * MB ? 1 : 0) + " MB";
    }

    function isImage(file) { return IMAGE_TYPES.indexOf(file.type) >= 0 || /\.(png|jpe?g|gif|webp|bmp)$/i.test(file.name); }
    function isVideo(file) { return file.type.indexOf("video/") === 0 || /\.(mp4|m4v|webm|mov|ogv)$/i.test(file.name); }

    function textInput(value, placeholder, extraClass) {
        var input = h("input", { type: "text", maxlength: "255", placeholder: placeholder, class: extraClass || "" });
        input.value = value || "";
        input.addEventListener("input", changed);
        return input;
    }

    // --- uploads -------------------------------------------------------------------

    function setPending(delta) {
        pending += delta;
        setButtons(pending > 0);
        status.textContent = pending ? "Качване на файлове (" + pending + ")… Изчакайте, преди да запазите." : statusText;
    }

    function progressBar() {
        var bar = h("div", { class: "upload-progress__bar" });
        var text = h("p", { class: "upload-progress__text", text: "Качване…" });
        var box = h("div", { class: "upload-progress" }, [h("div", { class: "upload-progress__track" }, [bar]), text]);
        return {
            node: box,
            update: function (loaded, total) {
                var percent = Math.round(loaded * 100 / total);
                bar.style.width = percent + "%";
                text.textContent = percent + "% (" + formatMb(loaded) + " от " + formatMb(total) + ")";
                if (loaded === total) {
                    box.classList.add("is-processing");
                    text.textContent = "Обработка…";
                }
            }
        };
    }

    // handlers: progress(loaded, total), done(item, warning), fail(message)
    function upload(file, kind, handlers) {
        var limit = config.limits[kind];
        if (file.size > limit * MB) {
            handlers.fail("„" + file.name + "“ е " + formatMb(file.size) + ", а максимумът е " + limit + " MB."
                + (kind === "video" ? " Намалете видеото (напр. 720p) или го разделете." : ""));
            return;
        }
        var data = new FormData();
        data.append("file", file, file.name || "snimka.png");
        data.append("kind", kind);
        data.append("place", place ? place.value : "");
        data.append("csrfmiddlewaretoken", csrf());

        var xhr = new XMLHttpRequest();
        xhr.open("POST", config.uploadUrl);
        xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
        setPending(1);
        xhr.upload.addEventListener("progress", function (e) {
            if (e.lengthComputable) handlers.progress(e.loaded, e.total);
        });
        xhr.addEventListener("load", function () {
            setPending(-1);
            var answer = null;
            try { answer = JSON.parse(xhr.responseText); } catch (e) { /* not JSON, e.g. logged out */ }
            if (xhr.status === 200 && answer && answer.item) {
                changed();
                handlers.done(answer.item, answer.warning);
            } else if (xhr.status === 413) {
                handlers.fail("„" + file.name + "“ е по-голям, отколкото сървърът приема. Намалете го (или разделете видеото) и опитайте пак.");
            } else if (xhr.status >= 500) {
                handlers.fail("Грешка на сървъра: „" + file.name + "“ не е качен. Опитайте пак след малко; ако се повтаря, обадете се на администратора.");
            } else {
                handlers.fail(answer && answer.error ? answer.error
                    : "„" + file.name + "“ не е качен. Опитайте отново (ако сте излезли от системата, влезте пак в нов таб).");
            }
        });
        xhr.addEventListener("error", function () {
            setPending(-1);
            handlers.fail("Връзката прекъсна и „" + file.name + "“ не е качен. Опитайте отново.");
        });
        xhr.send(data);
    }

    // --- fields used by the blocks -------------------------------------------------

    function richText(html, placeholder, onFiles) {
        var area = h("div");
        area.innerHTML = html || "";
        var field = {
            node: h("div", { class: "eblock__rich" }, [area]),
            mount: function () {
                field.quill = new Quill(area, {
                    theme: "snow",
                    placeholder: placeholder,
                    formats: ["bold", "italic", "list", "link"],
                    modules: {
                        toolbar: TOOLBAR,
                        // Pictures pasted or dropped into the text go to the block's pictures instead.
                        uploader: { mimetypes: IMAGE_TYPES, handler: function (range, files) { onFiles(Array.prototype.slice.call(files)); } }
                    }
                });
                var toolbar = field.quill.getModule("toolbar").container;
                Object.keys(TOOL_TITLES).forEach(function (selector) {
                    var button = toolbar.querySelector(selector);
                    if (button) button.title = TOOL_TITLES[selector];
                });
                var linkInput = field.quill.theme.tooltip.textbox;
                if (linkInput) linkInput.setAttribute("data-link", "https://...");
                field.quill.on("text-change", changed);
            },
            html: function () {
                return field.quill && field.quill.getText().trim() ? field.quill.getSemanticHTML() : "";
            }
        };
        return field;
    }

    // Pictures of a step (several, in order) or of a picture block (single).
    function picturesField(items, block, single) {
        var grid = h("div", { class: "epics" + (single ? " epics--single" : "") });
        var input = h("input", { type: "file", accept: "image/*", multiple: !single, hidden: true });
        var button = h("button", { type: "button", class: "button-secondary button-small", onclick: function () { input.click(); } });
        var hint = h("span", { class: "muted small", text: "или плъзнете / поставете с Ctrl+V" });

        function current() {
            return Array.prototype.filter.call(grid.children, function (tile) { return tile._item; });
        }
        function update() {
            var count = current().length;
            button.textContent = single ? (count ? "Смени снимката" : "Избери снимка") : "+ Добави снимки";
            grid.hidden = !grid.children.length;
        }
        function tile(item) {
            var node = h("figure", { class: "epic" }, [h("img", { src: item.thumb, alt: item.title || "" })]);
            var tools = h("div", { class: "epic__tools" });
            if (!single) {
                tools.appendChild(h("button", { type: "button", title: "Наляво", "aria-label": "Премести снимката наляво", text: "←", onclick: function () {
                    if (node.previousElementSibling) { grid.insertBefore(node, node.previousElementSibling); changed(); }
                } }));
                tools.appendChild(h("button", { type: "button", title: "Надясно", "aria-label": "Премести снимката надясно", text: "→", onclick: function () {
                    if (node.nextElementSibling) { grid.insertBefore(node.nextElementSibling, node); changed(); }
                } }));
            }
            tools.appendChild(h("button", { type: "button", class: "epic__remove", title: "Махни снимката", "aria-label": "Махни снимката", text: "✕", onclick: function () {
                node.remove(); changed(); update();
            } }));
            node.appendChild(tools);
            node._item = item;
            return node;
        }
        // Uploads the pictures among the files; returns the files it did not take.
        function add(files) {
            var images = files.filter(isImage);
            var rest = files.filter(function (f) { return !isImage(f); });
            if (single && images.length) {
                rest = images.slice(1).concat(rest);
                images = images.slice(0, 1);
            }
            images.forEach(function (file) {
                var bar = progressBar();
                var placeholder = h("figure", { class: "epic epic--loading" }, [bar.node]);
                if (single) grid.textContent = "";
                grid.appendChild(placeholder);
                update();
                block.clearMessages();
                upload(file, "image", {
                    progress: bar.update,
                    done: function (item) {
                        if (placeholder.parentNode) grid.replaceChild(tile(item), placeholder);
                        update();
                    },
                    fail: function (message) {
                        placeholder.remove();
                        update();
                        block.message(message);
                    }
                });
            });
            return rest;
        }
        input.addEventListener("change", function () {
            // Through the block, like a drop: a file picked with „All files“ goes where it belongs.
            block.files(Array.prototype.slice.call(input.files));
            input.value = "";
        });
        items.forEach(function (item) { if (item && item.thumb) grid.appendChild(tile(item)); });
        update();
        return {
            node: h("div", { class: "epics-field" }, [grid, h("div", { class: "epics-field__add" }, [button, hint]), input]),
            add: add,
            items: function () { return current().map(function (t) { return t._item; }); }
        };
    }

    // The files of a step (PDF, Word, Excel…; several, in order). Videos go in a video block.
    function stepFilesField(items, block) {
        var list = h("div", { class: "efiles" });
        var input = h("input", { type: "file", multiple: true, hidden: true,
            accept: config.fileTypes.map(function (e) { return "." + e; }).join(",") });
        var button = h("button", { type: "button", class: "button-secondary button-small", text: "+ Добави файл",
            onclick: function () { input.click(); } });
        var hint = h("span", { class: "muted small", text: "PDF, Word, Excel… до " + config.limits.file + " MB" });

        function row(item) {
            var node = h("div", { class: "efile" }, [
                h("strong", { text: item.name || item.title }),
                h("span", { class: "muted small", text: item.size ? " · " + formatMb(item.size) : "" }),
                h("button", { type: "button", class: "efile__remove", title: "Махни файла", "aria-label": "Махни файла", text: "✕",
                    onclick: function () { node.remove(); changed(); update(); } })
            ]);
            node._item = item;
            return node;
        }
        function current() {
            return Array.prototype.filter.call(list.children, function (node) { return node._item; });
        }
        function update() { list.hidden = !list.children.length; }
        // Uploads the files that aren't pictures or videos; returns the ones it did not take.
        function add(files) {
            var mine = files.filter(function (f) { return !isImage(f) && !isVideo(f); });
            mine.forEach(function (file) {
                var bar = progressBar();
                var placeholder = h("div", { class: "efile efile--loading" }, [bar.node]);
                list.appendChild(placeholder);
                update();
                block.clearMessages();
                upload(file, "file", {
                    progress: bar.update,
                    done: function (item) {
                        if (placeholder.parentNode) list.replaceChild(row(item), placeholder);
                        update();
                    },
                    fail: function (message) {
                        placeholder.remove();
                        update();
                        block.message(message);
                    }
                });
            });
            return files.filter(function (f) { return mine.indexOf(f) < 0; });
        }
        input.addEventListener("change", function () {
            block.files(Array.prototype.slice.call(input.files));  // a picture or video picked here: see above
            input.value = "";
        });
        items.forEach(function (item) { if (item && item.id) list.appendChild(row(item)); });
        update();
        return {
            node: h("div", { class: "efiles-field" }, [list, h("div", { class: "epics-field__add" }, [button, hint]), input]),
            add: add,
            items: function () { return current().map(function (n) { return n._item; }); }
        };
    }

    // The video of a video block, or the file of a file block.
    function documentField(kind, item, block) {
        var accept = kind === "video" ? "video/*,.mp4,.m4v,.webm,.mov"
            : config.fileTypes.map(function (e) { return "." + e; }).join(",");
        var input = h("input", { type: "file", accept: accept, hidden: true });
        var info = h("div", { class: "edoc__info" });
        var button = h("button", { type: "button", class: "button-secondary button-small", onclick: function () { input.click(); } });
        var progress = h("div");
        var value = item && item.id ? item : null;

        function render() {
            info.textContent = "";
            if (value) {
                info.appendChild(h("strong", { text: value.name || value.title }));
                if (value.size) info.appendChild(h("span", { class: "muted small", text: " · " + formatMb(value.size) }));
                button.textContent = kind === "video" ? "Смени видеото" : "Смени файла";
            } else {
                info.appendChild(h("span", { class: "muted", text: kind === "video"
                    ? "Изберете видео (MP4, до " + config.limits.video + " MB) или го плъзнете тук."
                    : "Изберете файл (PDF, Excel, Word…, до " + config.limits.file + " MB) или го плъзнете тук." }));
                button.textContent = kind === "video" ? "Избери видео" : "Избери файл";
            }
        }
        function add(file) {
            var bar = progressBar();
            progress.appendChild(bar.node);
            button.disabled = true;
            block.clearMessages();
            upload(file, kind, {
                progress: bar.update,
                done: function (uploaded, warning) {
                    bar.node.remove();
                    button.disabled = false;
                    value = uploaded;
                    render();
                    if (warning) block.message(warning, true);
                },
                fail: function (message) {
                    bar.node.remove();
                    button.disabled = false;
                    block.message(message);
                }
            });
        }
        input.addEventListener("change", function () {
            if (input.files.length) add(input.files[0]);
            input.value = "";
        });
        render();
        return {
            node: h("div", { class: "edoc" }, [h("div", { class: "edoc__row" }, [info, button]), progress, input]),
            add: add,
            value: function () { return value; }
        };
    }

    // --- blocks --------------------------------------------------------------------

    var BUILDERS = {
        step: function (block, data) {
            var title = textInput(data.title, "Какво да се направи, напр. „Отворете Настройки“", "eblock__title");
            var pictures = picturesField(data.images || [], block, false);
            var attached = stepFilesField(data.files || [], block);
            var text = richText(data.html, "Подробности (по желание)", function (files) { block.files(files); });
            block.body.appendChild(title);
            block.body.appendChild(text.node);
            block.body.appendChild(pictures.node);
            block.body.appendChild(attached.node);
            text.mount();
            block.files = function (files) {
                var rest = attached.add(pictures.add(files));  // videos: a video block below
                if (rest.length) addFileBlocks(rest, block);
            };
            block.focus = function () { title.focus(); };
            block.serialize = function () {
                return { type: "step", title: title.value, html: text.html(), images: pictures.items(), files: attached.items() };
            };
            block.isEmpty = function () {
                return !title.value.trim() && !text.html() && !pictures.items().length && !attached.items().length;
            };
        },
        text: function (block, data) {
            var text = richText(data.html, "Текст…", function (files) { addFileBlocks(files, block); });
            block.body.appendChild(text.node);
            text.mount();
            block.focus = function () { text.quill.focus(); };
            block.serialize = function () { return { type: "text", html: text.html() }; };
            block.isEmpty = function () { return !text.html(); };
        },
        heading: function (block, data) {
            var input = textInput(data.text, "Подзаглавие, напр. „Ако проблемът остане“", "eblock__title");
            block.body.appendChild(input);
            block.focus = function () { input.focus(); };
            block.serialize = function () { return { type: "heading", text: input.value }; };
            block.isEmpty = function () { return !input.value.trim(); };
        },
        image: function (block, data) {
            var picture = picturesField(data.image ? [data.image] : [], block, true);
            var caption = textInput(data.caption, "Надпис под снимката (по желание)");
            block.body.appendChild(picture.node);
            block.body.appendChild(caption);
            block.files = function (files) {
                var rest = picture.add(files);
                if (rest.length) addFileBlocks(rest, block);
            };
            block.focus = function () { caption.focus(); };
            block.serialize = function () { return { type: "image", image: picture.items()[0] || null, caption: caption.value }; };
            block.isEmpty = function () { return !picture.items().length && !caption.value.trim(); };
        },
        video: function (block, data) {
            var video = documentField("video", data.document, block);
            var caption = textInput(data.caption, "Надпис под видеото (по желание)");
            block.body.appendChild(video.node);
            block.body.appendChild(caption);
            block.files = function (files) {
                var videos = files.filter(isVideo);
                if (videos.length) video.add(videos[0]);
                var rest = files.filter(function (f) { return f !== videos[0]; });
                if (rest.length) addFileBlocks(rest, block);
            };
            block.focus = function () { caption.focus(); };
            block.serialize = function () { return { type: "video", document: video.value(), caption: caption.value }; };
            block.isEmpty = function () { return !video.value() && !caption.value.trim(); };
        },
        note: function (block, data) {
            var select = h("select", { "aria-label": "Вид бележка", onchange: function () { changed(); paint(); } },
                NOTE_STYLES.map(function (style) { return h("option", { value: style[0], text: style[1] }); }));
            select.value = data.style || "info";
            var text = richText(data.html, "Текст на бележката…", function (files) { addFileBlocks(files, block); });
            block.body.appendChild(h("label", { class: "eblock__inline" }, [document.createTextNode("Вид: "), select]));
            block.body.appendChild(text.node);
            text.mount();
            function paint() { block.node.dataset.style = select.value; }
            paint();
            block.focus = function () { text.quill.focus(); };
            block.serialize = function () { return { type: "note", style: select.value, html: text.html() }; };
            block.isEmpty = function () { return !text.html(); };
        },
        file: function (block, data) {
            var file = documentField("file", data.document, block);
            var title = textInput(data.title, "Текст на бутона (по желание, иначе името на файла)");
            block.body.appendChild(file.node);
            block.body.appendChild(title);
            block.files = function (files) {
                var first = files.filter(function (f) { return !isImage(f) && !isVideo(f); })[0];
                if (first) file.add(first);
                var rest = files.filter(function (f) { return f !== first; });
                if (rest.length) addFileBlocks(rest, block);
            };
            block.focus = function () { title.focus(); };
            block.serialize = function () { return { type: "file", document: file.value(), title: title.value }; };
            block.isEmpty = function () { return !file.value() && !title.value.trim(); };
        }
    };

    function toolButton(text, label, onclick) {
        return h("button", { type: "button", class: "eblock__tool", title: label, "aria-label": label, text: text, onclick: onclick });
    }

    function createBlock(type, data, before) {
        var block = { type: type };
        var messages = h("div", { class: "eblock__messages" });
        block.label = h("span", { class: "eblock__label", text: LABELS[type] });
        block.body = h("div", { class: "eblock__body" });
        block.node = h("section", { class: "eblock eblock--" + type }, [
            h("header", { class: "eblock__head" }, [block.label, h("div", { class: "eblock__tools" }, [
                toolButton("↑", "Премести нагоре", function () { move(block, -1); }),
                toolButton("↓", "Премести надолу", function () { move(block, 1); }),
                toolButton("✕", "Махни блока", function () { removeBlock(block); })
            ])]),
            block.body,
            messages
        ]);
        block.message = function (text, isWarning) {
            messages.appendChild(h("p", { class: isWarning ? "eblock__warning" : "field-error", text: text }));
        };
        block.clearMessages = function () { messages.textContent = ""; };
        // Text, heading and note blocks put dropped/pasted files in new blocks below them.
        block.files = function (files) { addFileBlocks(files, block); };
        block.node._block = block;
        list.insertBefore(block.node, before || null);
        BUILDERS[type](block, data || {});

        block.node.addEventListener("dragover", function (e) {
            if (hasFiles(e)) { e.preventDefault(); block.node.classList.add("is-dragging"); }
        });
        block.node.addEventListener("dragleave", function (e) {
            if (!block.node.contains(e.relatedTarget)) block.node.classList.remove("is-dragging");
        });
        block.node.addEventListener("drop", function (e) {
            block.node.classList.remove("is-dragging");
            if (e.defaultPrevented || !hasFiles(e)) return;  // Quill already took it
            e.preventDefault();
            block.files(Array.prototype.slice.call(e.dataTransfer.files));
        });
        block.node.addEventListener("paste", function (e) {
            if (e.defaultPrevented) return;  // Quill already took it
            var files = pastedImages(e);
            if (!files.length) return;
            e.preventDefault();
            block.files(files);
        });
        refresh();
        return block;
    }

    function hasFiles(e) {
        return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0;
    }

    function pastedImages(e) {
        var files = e.clipboardData ? Array.prototype.slice.call(e.clipboardData.files || []) : [];
        return files.filter(isImage);
    }

    // One new block per file, under `after` (a picture, video or file block, by type).
    function addFileBlocks(files, after) {
        var anchor = after;
        files.forEach(function (file) {
            var type = isImage(file) ? "image" : isVideo(file) ? "video" : "file";
            var block = createBlock(type, {}, anchor ? anchor.node.nextSibling : null);
            block.files([file]);
            anchor = block;
        });
        changed();
    }

    function blocks() {
        return Array.prototype.map.call(list.children, function (node) { return node._block; });
    }

    function refresh() {
        var number = 0;
        var all = blocks();
        all.forEach(function (block, index) {
            // Steps that follow each other are one numbered list on the site.
            number = block.type === "step" ? number + 1 : 0;
            if (block.type === "step") block.label.textContent = "Стъпка " + number;
            var tools = block.node.querySelectorAll(".eblock__tool");
            tools[0].disabled = index === 0;
            tools[1].disabled = index === all.length - 1;
        });
        empty.hidden = all.length > 0;
    }

    function move(block, step) {
        var node = block.node;
        if (step < 0 && node.previousElementSibling) list.insertBefore(node, node.previousElementSibling);
        else if (step > 0 && node.nextElementSibling) list.insertBefore(node.nextElementSibling, node);
        changed();
        refresh();
        node.scrollIntoView({ block: "nearest" });
    }

    function removeBlock(block) {
        if (!block.isEmpty() && !window.confirm("Да махна ли блока „" + block.label.textContent + "“ с цялото му съдържание?")) return;
        if (activeBlock === block) activeBlock = null;
        block.node.remove();
        changed();
        refresh();
    }

    // --- start -----------------------------------------------------------------------

    config.blocks.forEach(function (data) {
        if (BUILDERS[data.type]) createBlock(data.type, data);
    });

    // New blocks go under the block being worked on (or at the end).
    root.addEventListener("focusin", function (e) {
        var node = e.target.closest(".eblock");
        if (!node) return;
        if (activeBlock) activeBlock.node.classList.remove("is-active");
        activeBlock = node._block;
        node.classList.add("is-active");
    });
    root.querySelectorAll("[data-add]").forEach(function (button) {
        button.addEventListener("click", function () {
            var before = activeBlock && activeBlock.node.parentNode ? activeBlock.node.nextSibling : null;
            var block = createBlock(button.dataset.add, {}, before);
            changed();
            block.node.scrollIntoView({ block: "center", behavior: "smooth" });
            block.focus();
        });
    });

    // Files dropped next to the blocks, or a picture pasted outside them (e.g. in the title).
    root.addEventListener("dragover", function (e) { if (hasFiles(e)) e.preventDefault(); });
    root.addEventListener("drop", function (e) {
        if (e.defaultPrevented || !hasFiles(e)) return;
        e.preventDefault();
        addFileBlocks(Array.prototype.slice.call(e.dataTransfer.files), activeBlock);
    });
    form.addEventListener("paste", function (e) {
        if (e.defaultPrevented) return;
        var files = pastedImages(e);
        if (!files.length) return;
        e.preventDefault();
        addFileBlocks(files, activeBlock);
    });
    // A file dropped anywhere else must not replace the page (and lose the work).
    window.addEventListener("dragover", function (e) { if (hasFiles(e)) e.preventDefault(); });
    window.addEventListener("drop", function (e) { if (hasFiles(e)) e.preventDefault(); });

    form.addEventListener("input", changed);
    form.addEventListener("change", changed);
    form.addEventListener("submit", function (e) {
        if (pending > 0) {
            e.preventDefault();
            return;
        }
        output.value = JSON.stringify(blocks().map(function (block) { return block.serialize(); }));
        csrfField.value = csrf();
        // A disabled button isn't sent, so its choice goes in a hidden field.
        var pressed = e.submitter || buttons[0];
        var action = form.querySelector("input[type=hidden][name=action]") || document.createElement("input");
        action.type = "hidden";
        action.name = "action";
        action.value = pressed.value || "";
        form.appendChild(action);
        submitting = true;
        setButtons(true);
        pressed.textContent = "Запазване…";
    });
    // Back to this page after a save that didn't go through (e.g. the login page came instead):
    // the browser restores it as it was, so the button must work again.
    window.addEventListener("pageshow", function (e) {
        if (!e.persisted) return;
        submitting = false;
        setButtons(pending > 0);
    });
    window.addEventListener("beforeunload", function (e) {
        if ((dirty || pending) && !submitting) {
            e.preventDefault();
            e.returnValue = "";
        }
    });
    // Back from a failed save: keep the warning when leaving, the content wasn't saved yet.
    // and show the first thing to fix (the summary at the top says what happened).
    if (form.querySelector(".flash--error")) {
        dirty = true;
        var firstError = form.querySelector(".field-error");
        if (firstError) firstError.scrollIntoView({ block: "center" });
    }
})();
