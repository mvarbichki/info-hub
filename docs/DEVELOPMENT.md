# Developer reference

How the project is organised and how the main parts fit together. For running it locally see the
[README](../README.md), for servers [DEPLOY.md](../DEPLOY.md), for the tests
[tests/README.md](../tests/README.md). The user interface is in Bulgarian, so Bulgarian UI terms
are quoted below where they help find things on screen.

## Roles

| Role | Where | What they can do |
|---|---|---|
| **Venue staff** (`<place>_staff`) | the site only | Read the posts for all venues and for their venue. Read-only, 1-year session, cannot change their password. |
| **Venue manager** (`<place>_manager`) | the site only | The same, plus posts only for venue managers. |
| **Editor** (one or more per section) | `/manage/` | Write, edit, archive and delete the posts of their own section, manage its categories, see its statistics. |
| **Superuser** | `/manage/` + `/admin/` | Everything: all sections, „Важно“ (pinned posts), sections, venues, users; `/admin/` only for the logo, site name and footer. |

Venues and their accounts are managed in `/manage/` → Обекти / Потребители (several accounts per
venue and role are possible). An editor's section is the group „<Раздел> – редактори“ with page
permissions on that section (`dashboard/access.py`). Stopping a venue stops all its accounts at once
(`venues/backends.py`).

## Who sees which post

One module decides it: `guides/audience.py`. A post is for **all venues** (default), for the
**staff of chosen venues** (their managers see it too) or **only for the managers** of chosen
venues. Every list, search result, guide page, file download, statistic and „Често търсено“ chip
goes through `visible_guides` / `can_see` / `visible_media`; a post you may not see answers 404.

## Content model

```
Начало (HomePage: search, „Нови за вас“, „Важно“, latest, section cards)
├── Технически              DepartmentPage (a section)
│   ├── Принтери            CategoryPage (optional grouping)
│   │   └── Принтерът не печата   GuidePage
│   └── ...                 a GuidePage can also sit directly under a section
├── Казино система
├── Маркетинг
└── Персонал
```

Each **GuidePage** has a type (Ръководство / Новина / Кампания), a short summary, an audience and
a body of blocks: subheading, text, numbered steps (each with any number of pictures), image,
video, note (info / tip / warning) and file. In the code a section is a *department*
(`DepartmentPage`); the UI calls it „Раздел“.

## Project layout

| Path | What it is |
|---|---|
| `infohub/settings/` | `base.py` (database by environment: SQLite / PostgreSQL / MariaDB, limits), `dev.py`, `production.py` (environment, logging) |
| `infohub/access.py` | Login on every page, protected `/media/` with range requests and `X-Accel-Redirect`, noindex |
| `home/` | Home page, site settings (logo, name, footer), MariaDB charset check |
| `guides/models.py`, `guides/blocks.py` | Section, category and guide pages; content blocks |
| `guides/audience.py` | The visibility rule |
| `guides/editor.py`, `guides/media.py`, `guides/publishing.py` | Editor blocks ⇄ page body (with Wagtail's HTML whitelist), uploads, save / draft / archive / delete |
| `guides/departments.py` | Create, rename, order and delete sections (page + editors group + media folder) |
| `guides/management/commands/` | `setup_infohub`, `add_department`, `cleanup_media`, `export_site`, `import_site`, `make_previews`, `check_site` (read-only health check of the DB, files and who sees what) |
| `dashboard/` | The `/manage/` panel: one view module per tab, forms, templates |
| `venues/` | Venues, venue accounts, login-name suggestions, passwords |
| `search/views.py`, `search/variants.py` | Search (substring match that works with Bulgarian word endings); a word that finds nothing is retried in the other keyboard layouts (phonetic, БДС, ЙЦУКЕН), as Latin-to-Cyrillic, then as close words from the posts the user may see (typos) |
| `stats/` | Views, „Помогна ли ви?“ votes („Не“ needs a reason, shown in Статистика), searches per venue; „Нови за вас“ and „Прочетох“ per account |
| `guides/previews.py` | PDF copies of Word/Excel/PowerPoint/text/CSV uploads (text and CSV read as UTF-8, UTF-16 with its byte order mark, or Windows-1251, the CSV separator detected; an empty file gets none) (`DocumentPreview`), made with LibreOffice (`INFOHUB_SOFFICE`: "" = find it, a path, or "off"); shown in the post like a PDF (every in-page PDF is shown without the viewer's toolbar, `#toolbar=0`: larger page, and a copy's download can't hand out the PDF instead of the original to fill in), served with the file's access check; a spreadsheet's sheets each become one page of their own size (`SinglePageSheets`), so a wide table isn't cut into A4 pages; a sheet so long that its text comes out below 2 pt on that page is made again on A4 pages; `manage.py make_previews [--all]` for older files |
| `dashboard/views/history.py` | История of a post (Wagtail revisions + page log; older versions open in the editor with `?revision=`) and „Последни промени“ |
| `infohub/static/js/` | `editor.js` (block editor on Quill 2), `audience.js` (audience picker), `dashboard.js`, `infohub.js` |
| `infohub/static/css/infohub.css` | All styling |
| `deploy/`, `Dockerfile`, `docker-compose*.yml` | nginx, Caddy, container start and backup scripts |
| `tests/` | Django tests + jsdom tests of the JavaScript |

## Logo, site name and footer

`/admin/` → **Settings → Лого и име на сайта**. Until a logo is uploaded, the header shows a
dashed placeholder.

## Adding a section

Normally in the panel: `/manage/` → **Раздели** → „Създай раздел“ (superuser), then
**Потребители** → „Нов потребител“ with the role „Редактор“ and that section. ↑ ↓ in Раздели set
the order of the menu and the home page. The same from the command line:

```
python manage.py add_department "Финанси" finance --color purple --icon book
```

Both create the section page, a media folder for its pictures and videos (linked through
`guides.DepartmentMedia`, so renaming is safe) and the group „Финанси – редактори“.
Colours: blue, green, purple, orange, red, teal. Icons: computer, people, megaphone, info, tools, book.

## Admin language

The Bulgarian translation of the Wagtail admin is incomplete, so new accounts get `/admin/` in
English (each user can switch under Account → Preferences). The site and `/manage/` are Bulgarian.
