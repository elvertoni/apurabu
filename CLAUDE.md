# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Apura BU: apuração **extraoficial** para uma rádio, a partir dos QR Codes impressos nos boletins de urna (BU) do TSE. O projeto anda em etapas:

| Etapa | Onde | Situação nesta pasta |
|---|---|---|
| 1. Decodificador do QR do BU | `ferramentas/bu_qrcode.py` | presente |
| 2. App do celular (PWA) | `pwa/` | presente |
| 3. Servidor Django 5.2 + SQLite (`apuracao.tonicoimbra.com`) | `servidor/` (app `boletins`) | presente; em produção (ver Deploy) |
| 4. Painel da rádio | `/painel/` (`boletins/painel.py` + `templates/boletins/painel.html`) | presente; só equipe logada no admin |

Repositório Git: `https://github.com/elvertoni/apurabu.git`, branch principal `main`. Não há build, bundler, lint nem `package.json`: o PWA é HTML + ES modules puros.

`ferramentas/bu_qrcode.py` e `servidor/boletins/bu_qrcode.py` são cópias idênticas. Altere as duas.

## Comandos

```bash
# Testes do servidor (11). Dependências em servidor/requirements.txt
cd servidor && python manage.py test boletins
python manage.py test boletins.tests.ApiBoletinsTest.test_ping   # um teste só

# Decodificador Python com os 3 BUs reais (1º turno 2026). Exige o pacote `cryptography`.
python3 ferramentas/teste_bus_reais.py ferramentas/bus_reais_1turno_2026.json
# (sem argumento, o script procura `qr_raw.json`, que não existe)

# Paridade do decodificador JS (Node 20+, usa crypto.subtle global)
node --input-type=module -e "
import { LeitorBU, somar } from './pwa/bu.js'; import fs from 'node:fs';
const d = JSON.parse(fs.readFileSync('ferramentas/bus_reais_1turno_2026.json','utf8'));
const bus = [];
for (const ts of Object.values(d)) { const l = new LeitorBU(); ts.forEach(t => l.adicionar(t)); bus.push(await l.montar()); }
console.log(somar(bus).cargos.map(c => c.cargo + ':' + c.validos).join(' '));"

# Servir o PWA localmente (câmera só funciona em HTTPS; no localhost use "colar texto")
python3 -m http.server 8000 -d pwa
```

O JSON de teste mapeia `nome da foto -> [textos dos QR]` (3 `QRBU` + 2 `QRCE` por urna). Para testar outro cenário, gere um arquivo no mesmo formato.

## Formato do QR do BU (VRQR 6.0)

- Um BU = N QR `QRBU:n:N` + 2 QR `QRCE:n:2` (certificado X.509 da urna, em hex no campo `CERT:`).
- Conteúdo = tokens `CHAVE:VALOR` separados por espaço. Um bloco (ex.: partido) pode começar num QR e terminar no seguinte. Por isso o parser junta os dados de todos os QR antes de interpretar.
- Cabeçalho vem antes do primeiro `CARG`. Depois de `CARG`, os tokens pertencem ao cargo: `PART`/`LEGP`/`TOTP` (partido), chave numérica (votos do candidato), `APTA…TOTC` (totais do cargo).
- Integridade: `HASH` do QR i = SHA-512 de (conteúdo acumulado dos QR anteriores, no formato `<dados>HASH:<hash> `) + dados do QR i sem espaço final.
- Autenticidade: `ASSI` no último QR = ECDSA P-521/SHA-512 sobre os bytes do último `HASH`, verificada com o certificado (emissor deve conter `AC URNA`).
- Chave única da seção (anti-duplicidade): `pleito-turno-uf-municipio-zona-secao`.

## Arquitetura

**`bu_qrcode.py` e `pwa/bu.js` são espelhos.** Mudança no parsing, nas tabelas (`CARGOS`, totais) ou na validação precisa ir nos dois. Diferenças intencionais:
- JS não verifica a assinatura ECDSA; só a cadeia de hashes. A assinatura é verificada no servidor, que é a fonte da verdade.
- JS `adicionar()` retorna `'novo' | 'repetido' | 'conflito'`; Python levanta `ErroBU`.
- Campos do cabeçalho: `snake_case` no Python (`municipio_tse`), `camelCase` no JS (`municipioTse`).
- `bu.js` tem `somar()` (subtotal por cargo, ignora chave repetida) e `ORDEM_CARGOS` (ordem de exibição).

**Fluxo do PWA** (`pwa/app.js`):
1. Câmera: `BarcodeDetector` nativo (Android/Chrome) ou ponyfill ZXing-WASM (`vendor/`) para iPhone. O `locateFile` é sobrescrito para usar `vendor/zxing_reader.wasm` local em vez do CDN, para funcionar offline.
2. `receber()` descarta o mesmo texto lido nos últimos 4 s e alimenta um `LeitorBU`. Quando o BU fica completo, `concluir()` valida e grava no IndexedDB.
3. `QRCE` lido depois do BU completo é anexado ao registro já salvo. Se o registro já foi enviado, volta para `pendente`.
4. `agendarEnvio()` espera 5 s (tempo de ler o certificado) e faz `POST /api/boletins/` com `{chave, qrcodes, lido_em, reporter}`. Também reenvia em `online` e a cada 30 s.

**Armazenamento** (`pwa/db.js`):
- IndexedDB `apura-bu`, store `boletins`, `keyPath: "chave"`, status `pendente | enviado | erro`.
- Ajustes (`servidor`, `token`, `reporter`, `envio`) ficam em `localStorage["apura-ajustes"]`. Nomes de candidatos ficam em `localStorage["apura-nomes"]`.
- Mudar o schema do IndexedDB exige subir `VERSAO` e tratar `onupgradeneeded`.

**Service worker** (`pwa/sw.js`):
- Rede primeiro, cache como fallback. `/api/` nunca vem do cache.
- Ao alterar arquivos do app, suba `VERSAO` (`apura-bu-vN`).
- `cache.addAll(ARQUIVOS)` é tudo-ou-nada: se um arquivo da lista não existir, a instalação falha e o app deixa de funcionar offline. Mantenha `ARQUIVOS` igual aos arquivos reais. O nome esperado do WASM é exatamente `vendor/zxing_reader.wasm`.

**Configuração por link:** o servidor mostra um QR com `/app/#cfg=<JSON em base64url>` (`servidor`, `token`, `reporter`). Aberto direto em `https://…/app/` sem configuração, o app usa `location.origin` como servidor.

## Painel (`/painel/`)

- `PainelView` renderiza a página. `PainelDadosView` (`/painel/dados/?eleicao=&municipio=&local=<zona>/<numero>`) devolve o JSON. Ambos exigem usuário `is_staff`.
- `painel.dados_painel()` soma só os boletins `oficial=True` da UF `APURA_UF` (padrão `PR`). O resultado fica em cache por `APURA_PAINEL_CACHE` segundos (padrão 10, LocMem por worker).
- Urnas esperadas vêm de `LocalVotacao.secoes`. Nomes vêm de `Candidato`, pela UE do cargo (`BR`, UF ou município).
- A página atualiza a cada 20 s e monta o DOM só com `textContent`, porque nomes e repórter são dados externos. `?telao=1` abre o modo telão.
- O Django 5 guarda templates em cache: com `runserver --noreload`, uma mudança no template só aparece depois de reiniciar o servidor.

## Manual (`/manual/`)

`templates/boletins/manual.html` é o manual da equipe, servido por `TemplateView` sem login. É uma página estática, sem dados do banco, com links relativos ao próprio site. Ao mudar o sistema, atualize o manual e o `README.md` juntos.

## Contrato com o servidor

- Todas as rotas usam o cabeçalho `Authorization: Token <código do celular>`.
- `GET /api/ping/`: testar conexão.
- `POST /api/boletins/`: enviar um boletim. Deve responder 200/201 também para duplicado. 401/403 interrompe a fila. Outro 4xx marca `erro` com `detail`. 5xx ou falha de rede mantém `pendente`.
- `GET /api/nomes/`: mapa de nomes. Formato das chaves que o `app.js` realmente consulta:
  - candidato: `<UE>-<cargo>-<número>`; UE = `BR` (presidente), código TSE do município (cargos 11 e 13) ou UF (demais). Ex.: `PR-3-22`.
  - `L-<muni>-<zona>-<local>`: nome do local de votação.
  - `LS-<muni>-<zona>-<local>`: número de urnas esperadas no local.
  - `M-<muni>`: nome do município.

  `pwa/LEIA-ME.md` e o comentário no topo de `app.js` mostram outros formatos (`PR--3-22`, `PR-74454-1-22`). Vale o código de `nomeDe()`.
- Arquivo exportado ("Salvar arquivo"): `{formato: "apura-bu/1", gerado_em, reporter, boletins: [{chave, qrcodes, lido_em}]}`. O servidor importa esse arquivo em `/importar/`.

## Deploy (produção)

O `INSTALAR.md` descreve nginx + certbot, mas **a VPS real não usa esse caminho**. Nela, as portas 80/443 são do Traefik do Easypanel.

- VPS `161.97.69.249` (Ubuntu 24.04), acesso `ssh root@161.97.69.249`. Há outros sites nela: não mexa neles.
- Código em `/srv/apura_bu`, usuário `apura`, venv em `/srv/apura_bu/venv`, `.env` em `servidor/.env`.
- `apura.service` (systemd): gunicorn em `127.0.0.1:8010`.
- HTTPS pelo Cloudflare Tunnel do host (`/etc/cloudflared/config.yml`, regra `apuracao.tonicoimbra.com` → `http://localhost:8010`). O cloudflared envia `X-Forwarded-Proto: https`, que o `SECURE_PROXY_SSL_HEADER` usa.
- `/static/` é servido pelo WhiteNoise (não há nginx). Rode `collectstatic` depois de atualizar.
- Comandos de gerenciamento rodam como `apura` com o `.env` carregado:
  `cd /srv/apura_bu/servidor && sudo -u apura bash -c 'set -a; . ./.env; set +a; ../venv/bin/python manage.py <comando>'`
- Atualizar: envie os arquivos, rode `chown -R apura:www-data /srv/apura_bu`, `migrate`, `collectstatic` e `systemctl restart apura`.
- Base do TSE: `importar_tse --ano 2026 --so candidatos` e `importar_tse --ano 2026 --so locais --uf PR --turno N`. O CSV de locais traz uma linha por seção **e por turno**, e algumas seções mudam de escola entre os turnos. Reimporte os locais com `--turno 2` antes do 2º turno.
