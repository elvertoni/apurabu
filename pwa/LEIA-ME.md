# Apura BU — app do celular (Etapa 2)

App web instalável (PWA) para ler os QR Codes dos boletins de urna (BU).

## O que faz
- Lê os QR Codes pela câmera, com leitura contínua: basta ir descendo pela fita.
  - Android/Chrome usa o leitor nativo.
  - iPhone e outros navegadores usam o ZXing em WebAssembly (pasta `vendor/`), que funciona offline.
- Junta os 3 QR do boletim em qualquer ordem e valida a cadeia de hashes SHA-512.
  - Barra QR mal lido, adulterado ou de outra urna.
- Guarda tudo no próprio celular (IndexedDB) e mostra o **subtotal do local de votação** por cargo.
- Ignora seção lida duas vezes.
- Envia cada urna ao servidor da rádio 5 s depois de completa (tempo para ler o certificado).
  - Sem internet, guarda e reenvia sozinho quando a conexão volta.
- "Salvar arquivo" gera um `.json` com os QR brutos, para entregar na rádio.
- Funciona sem internet depois do primeiro acesso (service worker).

## Requisito
A câmera do celular só abre em **HTTPS**. Na Etapa 3, o Django na VPS vai servir esta pasta em `/app/`.

## Contrato com o servidor (Etapa 3)
| Método | Rota | Uso |
|---|---|---|
| `GET` | `/api/ping/` | testar conexão |
| `POST` | `/api/boletins/` | envia `{chave, qrcodes[], lido_em, reporter}` |
| `GET` | `/api/nomes/` | devolve `{"UF-MUNI-CARGO-NUMERO": "Nome"}` |

- Todas as rotas usam o cabeçalho `Authorization: Token <código do celular>`.
- No `POST /api/boletins/`:
  - o servidor revalida os QR (hash e assinatura) e é a fonte da verdade;
  - responde 200 ou 201 também para duplicados.
- O `GET /api/nomes/` usa a base de candidatos do TSE.
  - Chave sem município para cargos gerais, por exemplo `PR--3-22`.
  - Para presidente, `BR--1-22`.

## Teste local
```
python3 -m http.server 8000 -d pwa
```
No computador, `http://localhost:8000` funciona. Para testar a câmera, use a opção "colar texto".
