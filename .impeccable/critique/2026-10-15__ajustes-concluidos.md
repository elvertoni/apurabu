# Ajustes de interface concluídos

Implementação dos 12 achados da revisão Impeccable de 15/10/2026. Alterações locais no PWA, painel, manual, importação e administração; identidade azul-marinho/âmbar preservada.

| Achado | Correção |
|---|---|
| R01 — Envio manual | Proteção central em todos os gatilhos automáticos: leitura, reconexão, intervalo, inicialização e salvamento dos ajustes. O botão explícito continua disponível. |
| R02 — Estado da rádio | Separação entre ausência de internet, falta de configuração, acesso recusado, rádio sem resposta, envio e acesso confirmado. Cada boletim mostra recebimento; assinatura é indicada separadamente quando confirmada pelo servidor. |
| R03 — Contraste | Tokens próprios para texto, preenchimento e fundos de status em claro/escuro. Os pares semânticos medidos ficaram acima de 4,5:1. |
| R04 — Foco no painel | A região que contém o foco mantém seus nós enquanto a pessoa a utiliza. Outras regiões continuam atualizando; ao sair, a região recebe os dados mais recentes. |
| R05 — Dicas dos candidatos | Escape fecha; o ponteiro pode entrar na dica; descrição associada ao elemento que a abriu. |
| R06 — Rótulos | Rótulo persistente na colagem de QR, identificação do arquivo de importação e nome contextual no checkbox de acompanhamento de cada eleição. |
| R07 — Anúncios | Resultados de salvar/testar conexão e progresso de leitura/envio usam regiões de status. Falhas importantes ficam disponíveis para correção. |
| R08 — Controles e navegação | Controles recorrentes ampliados, estado atual das quatro telas exposto e ícones SVG consistentes. |
| R09 — Layout móvel | Câmera compacta antes da ativação; marca sem quebra; indicadores em duas colunas no móvel; atalhos Resultados/Cobertura/Equipe com foco no destino. |
| R10 — Recuperação | Confirmação ao descartar leitura incompleta, texto colado preservado após rejeição, importação com mensagens distintas de sucesso/falha/aceitação parcial e entradas malformadas recusadas sem interromper itens válidos. |
| R11 — Ajuda | Ajuda contextual no PWA, orientação de configuração inicial e manual organizado por repórter, estúdio e coordenação. |
| R12 — Tipografia e continuidade | Hierarquia utilitária consistente, campos com fonte de 16px, números tabulares, administração/importação com navegação e identidade compartilhadas e fallback de candidato sem número duplicado. |

Também atualizados README, manual e versão do cache do service worker (`apura-bu-v3`). Nenhuma alteração nos decodificadores ou no esquema do banco.

## Verificação

- **17 testes Django passaram**, incluindo três regressões novas da importação: arquivo inválido sem sucesso enganoso, lista malformada e aceitação parcial sem perda dos itens válidos.
- **49 verificações de navegador passaram**, com dados locais: envio manual após reconexão/intervalo/reinício, envio explícito, recuperação de credencial recusada, envio automático, conservação de entrada, cancelamento de descarte, estado de navegação, contraste claro/escuro, foco, tooltip, importação e layout em 360/390/768/1440px.
- O PWA reabriu offline com o service worker atualizado. O painel manteve o layout com ampliação de texto por CSS; isso não substitui um ensaio completo com zoom nativo de navegador.
- Nenhum erro JavaScript de página nos fluxos exercitados. Sintaxe de JavaScript conferida com Node.
- Detector Impeccable executado uma vez na implementação: desapareceu o achado de contraste; os sete avisos restantes são contextuais no manual (dois de rótulos em maiúsculas e cinco de recuos aplicados nos elementos filhos).

Resultados detalhados: [navegador](evidence/after/browser-results.json), [detector](evidence/after/detector.json).

Capturas: [leitura móvel](evidence/after/pwa-ler-light.png), [leitura escura](evidence/after/pwa-ler-dark.png), [importação móvel](evidence/after/importar-mobile-final.png).

## Limites

Validação local em Chromium. Não houve publicação na VPS, teste físico de câmera/toque, VoiceOver/NVDA ou certificação WCAG. Dados, usuários e credenciais de validação foram temporários. Não foi atribuída nova nota de design; isso exigiria uma nova avaliação independente.
