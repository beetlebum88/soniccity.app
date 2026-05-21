# SonicCity Deployment

Production domain: `soniccity.app`

## Required VPS Access

- SSH host/IP.
- SSH user with `sudo` access.
- SSH key allowed for that user, or a temporary password.
- Deploy path, default: `/var/www/soniccity.app`.
- Confirmation whether the VPS uses `nginx` + `systemd`.
- DNS access or confirmation that `soniccity.app` points to the VPS.

## Required Production Env

Create `/var/www/soniccity.app/.env` on the server from `.env.example`.

Important values:

- `APP_ENV=production`
- `SECRET_KEY=<strong-random-secret>`
- `SITE_DOMAIN=soniccity.app`
- `SITE_URL=https://soniccity.app`
- `APP_URL=https://soniccity.app`
- `ADMIN_EMAIL=<owner-email>`
- `ADMIN_PASSWORD_HASH=<werkzeug-password-hash>`
- `CONTACT_EMAIL=info@soniccity.app`
- SMTP values for email delivery
- `OPENAI_API_KEY=<server-side-key>`
- `AUDIO_STORAGE_PATH=static/audio`
- `GLOBAL_NOINDEX=1` while testing on VPS

Switch `GLOBAL_NOINDEX=0` only when indexing is intentionally opened.

## First Deploy Commands

```bash
sudo mkdir -p /var/www
sudo chown -R "$USER":www-data /var/www
git clone https://github.com/beetlebum88/soniccity.app.git /var/www/soniccity.app
cd /var/www/soniccity.app
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
mkdir -p static/audio static/uploads logs cache data/admin
cp .env.example .env
```

Edit `.env` on the server before starting the app.

## Systemd

```bash
sudo cp deploy/systemd/soniccity.service /etc/systemd/system/soniccity.service
sudo systemctl daemon-reload
sudo systemctl enable soniccity
sudo systemctl start soniccity
sudo systemctl status soniccity
```

## Nginx

```bash
sudo cp deploy/nginx/soniccity.app.conf /etc/nginx/sites-available/soniccity.app
sudo ln -s /etc/nginx/sites-available/soniccity.app /etc/nginx/sites-enabled/soniccity.app
sudo nginx -t
sudo systemctl reload nginx
```

## SSL

```bash
sudo certbot --nginx -d soniccity.app -d www.soniccity.app
```

## Update Deploy

```bash
cd /var/www/soniccity.app
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart soniccity
```
