# Deploying

Three ways to run the site:

- **Internet with HTTPS on a VM** (e.g. the free Oracle Cloud tier): the section right below, step by step.
- **The Docker setup itself** (sections 1–8, first written for a VM inside a VPN, plain http).
- **Shared hosting with MariaDB** (cPanel, Passenger): at the end of this page.

The whole site moves between them with two commands, `export_site` / `import_site`.

## Demo on Oracle Cloud (internet, HTTPS)

```
Browser ──https──► VM :443 ── Caddy (certificate) ──► nginx ──► web (Wagtail) ──► db (PostgreSQL)
```

**A. The VM.** Sign up at cloud.oracle.com (a card is needed to verify; "Always Free" resources are
not charged). Compute → Instances → Create instance:
- Image **Canonical Ubuntu 24.04**, shape **VM.Standard.A1.Flex** (Ampere, Always Free) with
  2 OCPU / 12 GB memory; boot volume 100 GB (Always Free allows 200 GB in total).
- Add your SSH key (on Windows: `ssh-keygen` in PowerShell, upload `C:\Users\<you>\.ssh\id_ed25519.pub`).
- After creating: note the **public IP**.
- Networking → the instance's subnet → Security List → Add ingress rules: source `0.0.0.0/0`,
  TCP ports **80** and **443**.

**B. A free name.** At duckdns.org log in, create e.g. `infohub-demo` and enter the VM's public IP
→ `infohub-demo.duckdns.org`. (A company subdomain works the same: an A record to the IP.)

**C. Docker** – SSH in (`ssh ubuntu@<public IP>`), then step **2** below. Instead of `ufw`, open
the ports in Oracle's firewall of the image:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

**D. The project** – straight from GitHub:

```bash
sudo mkdir -p /opt/infohub && sudo chown $USER /opt/infohub
git clone https://github.com/mvarbichki/info-hub.git /opt/infohub
```

(Without access to the repository: step **3** below, WinSCP or `tar` + `scp`.)

**E. Settings** – `cp .env.example .env`, `nano .env`:

```
DJANGO_SECRET_KEY=<openssl rand -base64 48>
SITE_DOMAIN=infohub-demo.duckdns.org
DJANGO_ALLOWED_HOSTS=infohub-demo.duckdns.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://infohub-demo.duckdns.org
DJANGO_HTTPS=1
WAGTAILADMIN_BASE_URL=https://infohub-demo.duckdns.org
POSTGRES_PASSWORD=<openssl rand -hex 24>
```

**F. Start with HTTPS:**

```bash
cd /opt/infohub
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
docker compose logs caddy | grep -i certificate     # "certificate obtained successfully"
```

**G. Move the site over** (venues, accounts with their passwords, departments, the demo posts):
on your PC, in the project folder:

```powershell
.venv\Scripts\python.exe manage.py export_site site.json
tar -czf media.tar.gz media
scp site.json media.tar.gz ubuntu@<public IP>:/tmp/
```

on the VM:

```bash
cd /opt/infohub
docker compose cp /tmp/site.json web:/tmp/site.json
docker compose exec web python manage.py import_site /tmp/site.json --yes
sudo tar -xzf /tmp/media.tar.gz -C /var/lib/docker/volumes/infohub_media/_data --strip-components=1
docker compose exec -u root web chown -R wagtail:wagtail /app/media
docker compose exec web rm /tmp/site.json; rm /tmp/site.json   # it holds the password hashes
```

and on your PC `del site.json`.

`import_site` prints the counts (24 обекта, 48 потребителя на обекти, …). Open
`https://infohub-demo.duckdns.org/login/`: the same logins and passwords as on your PC.

**H. Nightly job** – step **7** below (cleanup + database dump, cron).

**Before showing it:** the site is on the internet, so no venue account may keep a shared test password. In
Обекти → **„Нови пароли за всички обекти и лист за печат“** gives every venue its own password
(print the sheet) – or at least change the passwords of the accounts used in the demo.

**Updating** after changes have been pushed to GitHub (run the tests first: `manage.py test`, see
`tests/README.md`):

```bash
cd /opt/infohub
git pull
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
docker image prune -f
```

`.env` is not in the repository, so `git pull` never touches it.

## The Docker setup (sections 1–8, first written for the VPN)

The earlier variant: one Ubuntu VM inside the VPN, plain http.

One Ubuntu VM inside the VPN runs everything in Docker: the site (Wagtail + gunicorn),
the PostgreSQL database and nginx (serves pages, images and videos). All 22 venues open
the same address.

```
Venue browser ──VPN──► VM :80 ── nginx ──► web (Wagtail) ──► db (PostgreSQL)
                                   └── /static/; /media/ only after Django checks the login
```

## 1. Create the VM

| | |
|---|---|
| OS | **Ubuntu Server 24.04 LTS** |
| CPU / RAM | 2 vCPU, 4 GB RAM |
| Disk | 100 GB to start. Videos take most of the space, so plan more if you'll upload many. The nightly database dumps in `/srv/backups` are small. The superuser sees free space in `/manage/` (bottom of the page); it turns orange below 15% |
| Network | **Static IP** inside the VPN, reachable from all venues on port 80 |

During the Ubuntu install, tick **Install OpenSSH server**.

## 2. Install Docker

SSH into the VM (from Windows: `ssh youruser@10.0.0.15` in PowerShell) and run:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

Log out and back in (so the `docker` group applies), then check: `docker compose version`.

Firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw enable
```

## 3. Copy the project to the VM

Copy the project folder to `/opt/infohub` on the VM. **Do not copy** `.venv`,
`db.sqlite3` or `media/`. They are only for your PC.

The easiest way from Windows is **WinSCP** (SFTP to the VM, same login as SSH). Alternatively,
in PowerShell on your PC:

```powershell
# from the project folder
tar --exclude=.venv --exclude=db.sqlite3 --exclude=media --exclude=.idea --exclude=node_modules -czf infohub.tar.gz .
scp infohub.tar.gz youruser@10.0.0.15:/tmp/
```

then on the VM:

```bash
sudo mkdir -p /opt/infohub && sudo chown $USER /opt/infohub
tar -xzf /tmp/infohub.tar.gz -C /opt/infohub
```

(With access to the repository, `git clone` is simpler: see step **D** of the Oracle demo.)

## 4. Configure

```bash
cd /opt/infohub
cp .env.example .env
openssl rand -base64 48   # -> paste as DJANGO_SECRET_KEY
openssl rand -hex 24      # -> paste as POSTGRES_PASSWORD
nano .env
```

Set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` to the name and IP the venues
will use (e.g. `info.company.local` and `10.0.0.15`). A name that isn't listed gets a
"Bad Request (400)" page.

## 5. Start

```bash
docker compose up -d --build
docker compose exec web python manage.py setup_infohub
docker compose exec web python manage.py createsuperuser
```

`setup_infohub` also creates the users `marketing` and `cms` with the temporary passwords
`marketing` and `cms` (they must choose a new password at first login, so hand them over soon),
and the training venue „Обучение“ (logins `staff`, `manager`). Log in as the superuser at
`http://10.0.0.15/login/`, open **Обекти** and add the real venues, then **Потребители** and
create each venue's accounts (role, venue, suggested name like `pernik_staff`, password).

`.env` has `DJANGO_HTTPS=0` (plain http inside the VPN). With a certificate set it to `1`.

Useful commands:

```bash
docker compose ps              # are all 3 containers running?
docker compose logs -f web     # app logs (Ctrl+C to stop following)
docker compose restart web
```

The containers start automatically when the VM reboots.

## 6. Internal DNS name

Ask whoever manages DNS in the VPN to add an A record, e.g. `info.company.local → 10.0.0.15`,
so venues use a name instead of an IP. Make sure that name is in `.env`, then run
`docker compose up -d` again.

On each venue workstation, set the browser's start page (or a pinned tab or desktop
shortcut) to `http://info.company.local/`. With many machines, push it through Group Policy
(Edge/Chrome "Homepage" and "Startup pages" policies).

## 7. Backups

```bash
chmod +x /opt/infohub/deploy/backup.sh
sudo crontab -e
# add this line:
30 2 * * * /opt/infohub/deploy/backup.sh >> /var/log/infohub-backup.log 2>&1
```

Every night this first runs `cleanup_media` (deletes uploads nothing uses any more, page
versions older than 90 days and expired logins; try it by hand with
`docker compose exec web python manage.py cleanup_media --dry-run`), then saves a database dump
(14 days kept) to `/srv/backups/infohub/db/`.

The uploaded files (Docker volume `infohub_media`) are **not** copied separately: they are covered
by the backup of the whole VM (your backup software). The nightly dump adds a clean copy of the
database that is safe to restore even if the VM backup was taken while the database was writing.

Restore only the database (e.g. after a wrong delete), from a dump:

```bash
docker compose stop web
docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
gunzip -c /srv/backups/infohub/db/infohub_YYYY-MM-DD_HHMM.sql.gz | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose start web
```

Files deleted since that dump come back from the VM backup (restore the folder
`/var/lib/docker/volumes/infohub_media/_data/` from the same night).

## 8. Updating the site after code changes

Copy the changed files to `/opt/infohub` (same as step 3, keeping `.env`), then:

```bash
cd /opt/infohub
docker compose up -d --build
docker image prune -f    # remove the old image versions (each one is several hundred MB)
```

Note: `deploy/nginx.conf` allows uploads up to 320 MB. If you raise `INFOHUB_LIMITS_MB` in
`infohub/settings/base.py`, raise `client_max_body_size` there too.

Database changes (migrations) are applied automatically on start. Content and uploads
are not affected, because they live in Docker volumes.

## Error log

Server errors (with the full traceback of the failed page) and security warnings go to the
container log: `docker compose logs --tail 200 web`. Venue staff see a Bulgarian error page with
the time, so the matching entry is easy to find. On shared hosting set `INFOHUB_LOG_FILE` to a
path outside `public_html` (e.g. `/home/<user>/infohub-logs/errors.log`, folder created first): the
file rotates at 5 MB (5 old files kept) and can be read in cPanel's File Manager. "Not found"
pages are not logged (bots cause many).

## Optional: HTTPS

On the internet: `docker-compose.https.yml` (Caddy with Let's Encrypt), see the Oracle demo above.
Inside a VPN with an internal certificate instead: add a `listen 443 ssl` block to
`deploy/nginx.conf`, expose port 443 in `docker-compose.yml`, and switch the URLs in `.env` to
`https://`.

The login throttle counts per visitor: nginx passes the visitor's address in `X-Real-IP`
(`INFOHUB_CLIENT_IP_HEADER` in `docker-compose.yml`; with Caddy in front nginx takes it from
Caddy's `X-Forwarded-For`, trusting only Docker's own addresses). Without that every venue would
share one counter behind the proxy.

## Shared hosting with MariaDB (e.g. SuperHosting cPanel)

The full cPanel guide comes later; the database part is ready (tested on MariaDB 10.11).

1. In cPanel create the database and its user. Then, **before the first migrate**, in phpMyAdmin:
   ``ALTER DATABASE `<name>` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;``
   (MariaDB's default is latin1, which can't store Cyrillic. `migrate` refuses to run on a wrong
   database and prints this command: check `infohub.E001` in `home/checks.py`.)
2. Install with `pip install -r requirements-mariadb.txt`. It adds PyMySQL, a database driver that needs no C compiler (shared hosting has none, so `mysqlclient` fails with "Permission denied: gcc"); where `mysqlclient` is installed, it is used instead.
3. The settings go into a file **`.env` in the app's folder** (outside public_html, `chmod 600`).
   `passenger_wsgi.py` (the web app), `manage.py` (terminal, cron) read it, so there is one place
   for them: `DJANGO_SETTINGS_MODULE=infohub.settings.production`, `MARIADB_DB`, `MARIADB_USER`,
   `MARIADB_PASSWORD`, optional `MARIADB_HOST` (default `localhost`), `MARIADB_PORT` (3306),
   `MARIADB_COLLATION` (default `utf8mb4_unicode_ci`), the usual `DJANGO_*` ones,
   `INFOHUB_STATIC_ROOT` (the subdomain's document root + `/static`, so Apache serves CSS/JS
   itself; uploads stay in the app folder's `media/`, protected) and `INFOHUB_LOG_FILE` (see
   "Error log"). Variables set in cPanel's app page win over the file.

## Moving the whole site to another server

`export_site` writes everything (venues, all accounts with their password hashes, departments,
categories, posts with their versions, statistics, „Прочетох“) into one file; `import_site`
replaces the whole database of a new installation with it. Not moved: logins (everybody logs in
once more), the search index (rebuilt by `import_site`), the editing history of `/admin/`.
Copy the `media/` folder too. Works between SQLite, PostgreSQL and MariaDB (tested 2026-10-23
SQLite → MariaDB: 24 venues, 48 venue accounts, 11 posts, every venue account sees exactly its
posts and files, the same passwords log in).

```bash
python manage.py export_site site.json                # old server (or your PC)
python manage.py migrate                               # new server, empty database
python manage.py import_site site.json --yes           # replaces everything in the new database
```

`site.json` contains the password hashes: copy it securely and delete it afterwards.
