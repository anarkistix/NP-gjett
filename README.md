NP-gjett
========

Statisk webapp for Norge-omriss, admin og spill (nasjonalpark-quiz).

Lokalt
------

- Start statisk server:
  - `python3 -m http.server 8765 --bind 127.0.0.1`
- Start lagrings-API (for admin):
  - `python3 save_server.py`

Åpne:
- `http://127.0.0.1:8765/norge.html`
- `http://127.0.0.1:8765/admin.html`
- `http://127.0.0.1:8765/spill.html`

Deploy (GitHub Pages)
---------------------

- Repo må ha branch `main`
- Workflow `.github/workflows/pages.yml` bygger og publiserer hele repoet som statiske sider
- Aktiver Pages i GitHub: Settings → Pages → Source: GitHub Actions

Nettadresse blir `https://<bruker>.github.io/<repo>/spill.html` (og tilsvarende for andre sider).


