# Tests

One command checks the whole site on a separate, empty test database (the real venues, accounts
and posts in `db.sqlite3` are never touched):

```
.venv\Scripts\python.exe manage.py test
```

Run it before every change goes to a server. It takes about half a minute and ends with `OK`, or
names what broke. One part only: `manage.py test tests.test_audience` (file) or
`manage.py test tests.test_audience.VisibilityTests` (class).

| File | What |
|---|---|
| `base.py` | Shared setup: departments + editors (`setup_infohub`), venues Перник and София – Младост with staff + manager accounts, the training venue; helpers to log in, upload, save posts |
| `test_access.py` | Login for each role, pages behind the login, throttle (also behind the proxy), venue accounts can't change passwords, stopped venues, logout, expired forms |
| `test_editor.py` | Uploads, saving and cleaning posts, editing, every error message and where it shows, departments, moving, „Важно“, archive, delete, protected files (ranges), cleanup, counting |
| `test_audience.py` | Who sees which post (all / staff / only managers), labels, lists, search, files, chips, deleting venues, category pages |
| `test_reading.py` | Drafts and preview, „Нови за вас“, „Прочетох и запознах екипа“ (managers only, one per venue), „Прочитания“ |
| `test_panel.py` | Потребители, Обекти, password sheet, Раздели (incl. ↑ ↓ order), Категории, Статистика, login-name suggestions |
| `test_edges.py` | Edge cases: hostile text in titles/captions/names shown as text everywhere, login `next` to other sites ignored, odd search input, unknown ids, length limits, section order, `/django-admin/` gone |
| `test_settings.py` | Error log, 500 page, MariaDB check, setup commands |
| `test_previews.py` | Files inside a step, PDF copies of Word/Excel/PowerPoint/TXT/CSV (encoding incl. UTF-16, CSV separator, empty files, very long sheets on A4 pages, the shared time limit, made, shown, protected, deleted, `make_previews`, a sheet on one page); a real LibreOffice run where it is installed (also a wide table, TXT and CSV, a 20 000-row CSV) |
| `test_check_site.py` | `manage.py check_site`: OK on a healthy site, changes nothing, finds missing files, wrong rights, inconsistent audience, stale search text |
| `test_js.py` + `js/` | The site's JavaScript (editor, „Кой да я вижда“, „Нов потребител“, PDF inside a post) in jsdom on freshly rendered pages |

The JavaScript tests need [Node.js](https://nodejs.org/) and, once: `cd tests\js` → `npm install`.
Without them those two tests are skipped (the rest still run).

Coverage (which code the tests reach), with `pip install -r requirements-dev.txt`:

```
.venv\Scripts\python.exe -m coverage run --source=guides,dashboard,venues,stats,home,search,infohub --omit="*/migrations/*" manage.py test
.venv\Scripts\python.exe -m coverage report
```
