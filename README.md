# Apura BU

Apuração **parcial e extraoficial** para a rádio, feita a partir dos QR Codes impressos nos boletins de urna (BU) do TSE. O resultado oficial é sempre o divulgado pelo TSE.

Funciona assim:

1. O repórter lê os QR Codes do boletim com o celular (app **Apura BU**).
2. O app confere a integridade, guarda o boletim no celular e o envia ao servidor da rádio.
3. O servidor valida de novo (hash e assinatura digital da urna), descarta seções repetidas e soma tudo.
4. A equipe acompanha os números no **painel**, inclusive num telão no estúdio.

Em produção desde 14/10/2026 em **https://apuracao.tonicoimbra.com**.


## Interface e confirmação do envio

- **Envio automático:** tenta após a leitura completa, na reconexão e a cada 30 segundos.
- **Só quando eu mandar:** envia exclusivamente pelo botão **Enviar pendentes**, inclusive após reiniciar o app ou voltar a ter internet.
- **Acesso confirmado** informa que a rádio respondeu com autorização. A entrega de cada boletim aparece como **recebido pela rádio** na aba Envio.
- Se o código for recusado, use **Corrigir acesso**, salve o código correto em Ajustes e teste a conexão. Os boletins permanecem guardados no celular.
- Leituras incompletas pedem confirmação antes do descarte. Textos colados com erro são mantidos para correção.
- O painel oferece atalhos para **Resultados**, **Cobertura** e **Equipe**, preserva o foco da lista em uso nas atualizações e permite fechar dicas com **Esc**.
- O manual tem percursos para repórteres, estúdio e coordenação, com ajuda acessível nas abas do app.

---

## Endereços e acesso

| O quê | Endereço | Quem acessa |
|---|---|---|
| App do celular | https://apuracao.tonicoimbra.com/app/ | Repórteres, com o celular configurado pelo QR Code do admin |
| Manual da equipe | https://apuracao.tonicoimbra.com/manual/ | Qualquer pessoa, sem login |
| Painel de acompanhamento | https://apuracao.tonicoimbra.com/painel/ | Equipe com login no admin |
| Painel em modo telão | https://apuracao.tonicoimbra.com/painel/?telao=1 | Navegador do estúdio, logado no admin |
| Administração | https://apuracao.tonicoimbra.com/admin/ | Superusuário e equipe (`is_staff`) |
| Importar arquivo do celular | https://apuracao.tonicoimbra.com/importar/ | Equipe com login no admin |
| API | `/api/ping/`, `/api/boletins/`, `/api/nomes/`, `/api/totais/` | Celulares (cabeçalho `Authorization: Token <código>`) ou equipe logada |

- O endereço raiz (`/`) redireciona para o app.
- No admin, o link **"Ver o site"** abre o painel.
- O superusuário foi criado pelo administrador. A senha não está registrada em nenhum arquivo.
- Para criar outra pessoa da equipe: **Admin → Usuários → Adicionar**. Depois, marque **Membro da equipe** (`is_staff`), que basta para ver o painel e importar arquivos.

---

## Como usar no dia da eleição

### 1. Cadastrar os celulares (antes do dia)
1. Abra https://apuracao.tonicoimbra.com/equipe/ (só administradores).
2. Preencha o nome e, se quiser, o WhatsApp do repórter e toque em **Cadastrar e entregar acesso**. Para vários de uma vez, use **Cadastrar vários de uma vez**, um por linha (`Nome, (43) 99999-1234`).
3. Na janela de entrega, o repórter ao lado aponta a câmera para o QR Code. Longe, use **Enviar pelo WhatsApp** ou **Copiar** o link e mande só para ele.
4. O app abre já configurado com o servidor e o código de acesso. Na lista, o repórter passa de "Ainda não abriu o link" para "Abriu o app".
5. No celular, use **"Adicionar à tela inicial"** para instalar o app.
6. Na aba **Ajustes** do app, o botão **Testar conexão** confirma que está tudo certo.

### 2. Ler os boletins
- Toque em **Abrir câmera** e vá descendo pela fita do boletim. Os QR Codes podem ser lidos em qualquer ordem.
- O app avisa quando a urna está completa e validada. Depois, leia também os 2 QR Codes do **certificado**, que permitem ao servidor conferir a assinatura digital.
- Cada urna é enviada à rádio 5 segundos depois de completa.
- Sem internet, o app guarda tudo e reenvia sozinho quando a conexão volta. Ele tenta de novo a cada 30 segundos.
- Seção lida duas vezes é ignorada, tanto no celular quanto no servidor.
- A aba **Local** mostra o subtotal do que aquele celular leu.

### 3. Repórter sem internet
1. No app, aba **Envio**, toque em **Salvar arquivo**. É gerado um `.json` com os QR Codes brutos.
2. Entregue o arquivo na rádio.
3. Importe em https://apuracao.tonicoimbra.com/importar/. Todos os QR Codes são validados de novo, e seções já registradas são ignoradas.

### 4. Celular perdido ou link vazado
Em **Repórteres** (`/equipe/`), use **Gerenciar → Desativar acesso**. O celular para de enviar na hora.

Se o link de configuração caiu em mãos erradas, use **Gerenciar → Gerar novo código** e entregue o novo acesso. O código antigo para de funcionar, e os boletins já enviados continuam ligados ao celular. As mesmas ações existem em **Admin → Celulares autorizados**.

### 5. Acompanhar
Use o painel. Os detalhes estão na próxima seção.

---

## Painel (`/painel/`)

Mostra o **Paraná inteiro** por padrão e se atualiza sozinho a cada 20 segundos.

- **Indicadores no topo:**
  - urnas apuradas contra urnas esperadas, com barra de progresso;
  - comparecimento;
  - municípios com boletim, de 399;
  - alertas.
- **Presidente, Governador e Senador em destaque**, com nome de urna, partido, número, % dos votos válidos e votos.
  - Em presidente e governador, a barra vai de 0 a 100% e uma linha marca 50%, para ver se alguém vence no 1º turno.
  - Senador: quando cada eleitor vota em 2, o painel avisa que os percentuais somam 200%.
- **Deputado federal e estadual mais abaixo:** os 10 primeiros, "ver mais" até 50 e o total por partido (nominais + legenda).
- **Urnas apuradas por município.** Clique num município para ver as escolas dele.
- **Últimos boletins recebidos:** escola, município, repórter e situação da assinatura.
- **Celulares:** boletins enviados e último envio. Aparece um alerta quando um celular está há mais de 30 minutos sem enviar.
- **Filtros:** eleição, município e local de votação. O filtro fica no endereço da página, então dá para salvar o link.
- **Dica:** ao passar o mouse sobre um candidato, aparece a diferença de votos para o anterior e para o próximo da lista.
- **Modo telão:** botão no topo ou `?telao=1`. Abre em tela cheia, com letras grandes, só as urnas apuradas, o comparecimento e os três cargos principais.
- **Modo escuro:** segue o modo claro ou escuro do sistema.

**Regras da soma**
- Entram só boletins **oficiais** e do **PR**.
- Boletins simulados, de treinamento ou de outra UF aparecem nos alertas e ficam fora da soma.
- "Urnas esperadas" vem da base de locais de votação do TSE. Hoje ela está carregada com os dados do **2º turno**.
- O resultado tem sempre o aviso de "parcial e extraoficial".

---

## Instalação no servidor (o que existe hoje)

| Item | Valor |
|---|---|
| Servidor | VPS `161.97.69.249`, Ubuntu 24.04, Python 3.12 |
| Código | `/srv/apura_bu` (`servidor/`, `pwa/`, `ferramentas/`) |
| Usuário de sistema | `apura` (grupo `www-data`) |
| Ambiente Python | `/srv/apura_bu/venv` (Django 5.2.18, gunicorn, cryptography, segno, whitenoise) |
| Configuração | `/srv/apura_bu/servidor/.env` (`DJANGO_SECRET_KEY` aleatória, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_ORIGINS`) |
| Banco | SQLite em `/srv/apura_bu/servidor/db.sqlite3` |
| Serviço | `apura.service` (systemd), gunicorn com 3 workers em `127.0.0.1:8010`, sobe com o servidor |
| HTTPS | Cloudflare Tunnel já existente na VPS (`cloudflared`), certificado da Cloudflare renovado automaticamente |
| Rota do túnel | `/etc/cloudflared/config.yml`: `apuracao.tonicoimbra.com` → `http://localhost:8010` |
| DNS | CNAME `apuracao.tonicoimbra.com` → túnel, criado pelo `cloudflared` |
| Arquivos estáticos | Servidos pelo próprio Django (WhiteNoise) |

A VPS também hospeda outros sites (Easypanel, `tonicoimbra.com`, `prof.`, `gestao3d.`, `jogo.`). **Não mexa nas configurações deles.** As portas 80 e 443 pertencem ao Traefik do Easypanel. Por isso, este sistema **não usa nginx nem certbot**.

### Diferenças em relação ao `INSTALAR.md`
O `INSTALAR.md` é o guia genérico (nginx + certbot). Nesta VPS a instalação foi adaptada:

1. **Sem nginx e sem certbot.** O HTTPS vem do Cloudflare Tunnel. O backup da configuração anterior do túnel está em `/etc/cloudflared/config.yml.before-apuracao-20261014`.
2. **DNS:** o nome resolve para IPs da Cloudflare, não para o IP da VPS. Isso é o esperado com o túnel.
3. **WhiteNoise** foi adicionado em `config/settings.py` para servir `/static/`.
4. **`servidor/requirements.txt`** foi criado, com as versões fixadas.
5. **`.env`:** `DJANGO_ALLOWED_HOSTS` também aceita `127.0.0.1` e `localhost`, para testes locais no servidor.
6. **`importar_tse`** ganhou a opção `--turno` (explicada abaixo).

---

## Administração do servidor

Acesso: `ssh root@161.97.69.249` (somente o administrador).

Todos os comandos `manage.py` rodam como usuário `apura` e com o `.env` carregado:

```bash
cd /srv/apura_bu/servidor
sudo -u apura bash -c 'set -a; . ./.env; set +a; ../venv/bin/python manage.py <comando>'
```

| Tarefa | Comando |
|---|---|
| Ver se está no ar | `systemctl status apura` |
| Ver o log ao vivo | `journalctl -u apura -f` |
| Reiniciar | `systemctl restart apura` |
| Rodar os testes (14) | `manage.py test boletins` |
| Criar superusuário | `manage.py createsuperuser` (interativo) |
| Cópia de segurança do banco | `sudo -u apura ../venv/bin/python -c "import sqlite3; sqlite3.connect('db.sqlite3').backup(sqlite3.connect('../backup-$(date +%Y%m%d-%H%M).sqlite3'))"` |

Não há cópia de segurança automática do banco. No dia da eleição, vale fazer uma cópia antes de começar e outra depois.

### Atualizar o código
Na máquina de desenvolvimento, a partir da pasta do projeto:

```bash
tar --exclude=__pycache__ --exclude='*.pyc' --exclude=db.sqlite3 --exclude=.env \
    -czf - INSTALAR.md README.md ferramentas pwa servidor | ssh root@161.97.69.249 'tar -xzf - -C /srv/apura_bu'
```

> **Atenção:** nunca envie um `db.sqlite3` ou `.env` local. Eles sobrescreveriam o banco e a configuração de produção.

Depois, no servidor:

```bash
chown -R apura:www-data /srv/apura_bu
cd /srv/apura_bu/servidor
sudo -u apura bash -c 'set -a; . ./.env; set +a; ../venv/bin/python manage.py test boletins && ../venv/bin/python manage.py migrate && ../venv/bin/python manage.py collectstatic --noinput'
systemctl restart apura
```

Se mudar arquivos do app do celular (`pwa/`), suba a `VERSAO` em `pwa/sw.js`. Assim os celulares baixam a versão nova.

### Base do TSE (candidatos e locais de votação)

```bash
manage.py importar_tse --ano 2026 --so candidatos
manage.py importar_tse --ano 2026 --so locais --uf PR --turno 2
```

- O arquivo de locais do TSE traz **uma linha por seção e por turno**. No PR, 328 seções mudam de escola entre o 1º e o 2º turno. Por isso, os locais são importados de um turno de cada vez, com `--turno` (padrão 1).
- A importação dos locais substitui a anterior da mesma UF e ano.
- O comando baixa os arquivos para `/tmp` (cerca de 180 MB para os locais) e **não apaga o download**. Apague o arquivo à mão depois de conferir a importação.
- Para reaproveitar um download, use `--arquivo-locais <zip>` ou `--arquivo-candidatos <zip>`.

---

## O que foi feito (14 e 15/10/2026)

1. **Levantamento da VPS**, só leitura: sistema, portas, serviços e sites existentes. A porta 8010 estava livre. As portas 80 e 443 eram do Traefik, e já havia um Cloudflare Tunnel em uso.
2. **Instalação:**
   - usuário `apura`, venv, `.env` com chave secreta aleatória, `migrate` e `collectstatic`;
   - serviço `apura` no systemd;
   - `python3-venv` instalado pelo apt, sem reiniciar nenhum serviço de terceiros.
3. **Testes antes de publicar:** os 11 testes originais passaram.
4. **Publicação:**
   - rota nova no Cloudflare Tunnel, depois de fazer backup da configuração;
   - CNAME criado;
   - `cloudflared` reiniciado com autorização. Os outros sites voltaram normalmente.
5. **Conferências:**
   - `/app/` responde 200 por HTTPS;
   - `/api/ping/` com token inválido responde 401;
   - o Django reconhece o HTTPS, porque o túnel envia `X-Forwarded-Proto: https`. Assim, o QR Code de configuração do celular sai com `https://`.
6. **Importação do TSE:**
   - **Candidatos:** 20.780 candidatos e 30 partidos, dos quais 13 são candidatos a presidente. O leiaute bateu com o importador. A coluna "situação da candidatura" vem vazia (`#NE`) no próprio arquivo do TSE.
   - **Locais do PR:** a primeira importação contou seções em dobro (1º + 2º turno). O importador foi corrigido (`--turno`) e o teste correspondente foi reforçado.
   - **1º turno:** 4.823 locais, 27.142 urnas e 8.609.026 eleitores.
   - **2º turno (base atual):** 4.841 locais, 27.142 urnas e 8.609.026 eleitores, conferidos com o CSV do TSE.
   - **Escola de referência:** Colégio Estadual Nóbrega da Cunha (Bandeirantes, zona 58, local 1023), com 13 urnas e 3.368 eleitores.
7. **Painel de acompanhamento (`/painel/`)** foi criado, com modo telão, e testado no computador, no celular e no modo escuro. Agora são 13 testes automatizados.
8. **Manual da equipe (`/manual/`)** foi publicado no próprio site, aberto e sem login. Agora são 14 testes automatizados.

---

## Estrutura do código

```
pwa/                      app do celular (HTML + JavaScript, funciona offline)
  bu.js                   leitura e validação dos QR Codes no celular
  app.js, db.js, sw.js    telas, armazenamento local (IndexedDB) e modo offline
servidor/                 Django 5.2 + SQLite
  config/                 configurações (lidas do .env) e rotas
  boletins/
    bu_qrcode.py          decodificador do QR Code do BU (mesmo arquivo de ferramentas/)
    servicos.py           registrar boletim (revalida tudo) e totalizar
    painel.py             dados do painel
    views.py              API, importação, painel e app em /app/
    management/commands/importar_tse.py
    templates/boletins/   painel.html, manual.html (manual da equipe em /manual/) e importar.html
    tests.py              14 testes, incluindo 3 boletins reais do 1º turno de 2026
  deploy/                 apura.service e env.exemplo
ferramentas/              decodificador em Python e script de teste com BUs reais
```

Para desenvolver localmente:

```bash
cd servidor && python manage.py test boletins           # testes (requirements.txt)
python3 ferramentas/teste_bus_reais.py ferramentas/bus_reais_1turno_2026.json
```

Mais detalhes técnicos estão em `CLAUDE.md`, e o contrato do app com o servidor está em `pwa/LEIA-ME.md`. Vale uma ressalva sobre o `LEIA-ME.md`: as chaves de `/api/nomes/` que o código realmente usa têm o formato `BR-1-22` e `PR-3-55`, não `PR--3-22`.

---

## Pendências

- **Arquivos em `/tmp`:** a VPS tem um download do TSE de 175 MB (`/tmp/tmpnep7z8xt.zip`) e zips pequenos deixados pelos testes. Podem ser apagados.
- **Limpeza automática:** o `importar_tse` e os testes poderiam apagar sozinhos os arquivos temporários que criam.
- **Cópia de segurança:** não existe cópia automática do banco.
- **`check --deploy`:** avisa sobre HSTS e `SECURE_SSL_REDIRECT`. O redirecionamento de `http://` para `https://` já é feito pela Cloudflare.
