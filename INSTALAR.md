# Instalação na VPS — apuracao.tonicoimbra.com

Ubuntu + nginx + gunicorn + SQLite. Sem Docker. Faça um passo de cada vez e confira o resultado antes de seguir.

## Passo 1 — DNS
No painel do domínio `tonicoimbra.com`, crie um registro:

| Tipo | Nome | Valor |
|---|---|---|
| A | `apuracao` | IP da VPS |

Se usar Cloudflare, deixe a **nuvem cinza** (somente DNS) até o certificado do passo 6 sair.

**Conferir:**
```bash
dig +short apuracao.tonicoimbra.com
```
Deve mostrar o IP da VPS.

## Passo 2 — Pacotes e usuário
```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx unzip
sudo adduser --system --group --home /srv/apura_bu apura
```

## Passo 3 — Código
Envie o `apura-bu.zip` para a VPS:
```bash
scp apura-bu.zip usuario@IP:/tmp/
```

Depois, na VPS:
```bash
sudo unzip -o /tmp/apura-bu.zip -d /srv/apura_bu
sudo python3 -m venv /srv/apura_bu/venv
sudo /srv/apura_bu/venv/bin/pip install -r /srv/apura_bu/servidor/requirements.txt
```

## Passo 4 — Configuração e banco
```bash
cd /srv/apura_bu/servidor
sudo cp deploy/env.exemplo .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # copie e cole no DJANGO_SECRET_KEY
sudo nano .env
sudo chown -R apura:www-data /srv/apura_bu
sudo -u apura bash -c 'set -a; . ./.env; ../venv/bin/python manage.py migrate && ../venv/bin/python manage.py collectstatic --noinput'
sudo -u apura bash -c 'set -a; . ./.env; ../venv/bin/python manage.py createsuperuser'
```

## Passo 5 — Serviço (gunicorn)
```bash
sudo cp deploy/apura.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now apura
curl -sI http://127.0.0.1:8010/app/ | head -1
```
O `curl` deve responder `HTTP/1.1 200 OK`.

## Passo 6 — nginx + HTTPS
```bash
sudo cp deploy/nginx-apuracao.conf /etc/nginx/sites-available/apuracao.tonicoimbra.com
sudo ln -s /etc/nginx/sites-available/apuracao.tonicoimbra.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d apuracao.tonicoimbra.com
```
A câmera do celular **só funciona com HTTPS**. Depois de emitido o certificado, pode ligar a nuvem laranja da Cloudflare, no modo SSL "Full (strict)".

## Passo 7 — Base do TSE
Importe a base do TSE, tanto candidatos quanto escolas:
```bash
cd /srv/apura_bu/servidor
sudo -u apura bash -c 'set -a; . ./.env; ../venv/bin/python manage.py importar_tse --ano 2026'
```
- Para ir mais rápido nos locais de votação, use `--uf PR`.
- Repita o comando quando o TSE atualizar a base, ou na próxima eleição (ex.: `--ano 2028` para as municipais).

## Passo 8 — Celulares
1. Acesse `https://apuracao.tonicoimbra.com/admin/` → **Celulares autorizados** → Adicionar.
   - Cadastre um por repórter ou equipe.
2. Abra o cadastro e peça ao repórter para apontar a câmera do celular para o QR Code.
   - O app abre configurado.
3. No celular, use "Adicionar à tela inicial" para instalar o app.
4. Celular perdido: desmarque **Ativo**. Ele para de enviar na hora.

## Operação no dia
- **Arquivo trazido do celular** (repórter ficou sem internet): use `https://apuracao.tonicoimbra.com/importar/`.
- **Totais em JSON:** `/api/totais/`, com filtros `?municipio=74454`, `?local=1023` e `?zona=58`. O painel da rádio (Etapa 4) usa essa API.

## Atualizar o código depois
```bash
sudo unzip -o /tmp/apura-bu.zip -d /srv/apura_bu && sudo chown -R apura:www-data /srv/apura_bu
cd /srv/apura_bu/servidor && sudo -u apura bash -c 'set -a; . ./.env; ../venv/bin/python manage.py migrate'
sudo systemctl restart apura
```
