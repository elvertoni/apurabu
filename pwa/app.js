import { LeitorBU, ErroBU, identificar, somar } from "./bu.js";
import { db, ajustes } from "./db.js";

const $ = (s) => document.querySelector(s);
const fmt = (n) => n.toLocaleString("pt-BR");
const pct = (v, t) => (t ? (100 * v / t).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : "0,0") + "%";
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let leitor = new LeitorBU();
let regAtual = null;           // boletim já salvo, aguardando QRs do certificado
let nomes = carregarNomes();   // { "PR-74454-1-22": "Fulano" } — preenchido pelo servidor

// ------------------------------------------------------------------ navegação
document.querySelectorAll(".abas button").forEach((b) =>
  b.addEventListener("click", () => mostrar(b.dataset.tela)));

function mostrar(tela) {
  document.querySelectorAll(".abas button").forEach((b) => {
    const ativa = b.dataset.tela === tela;
    b.classList.toggle("ativa", ativa);
    if (ativa) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  document.querySelectorAll(".tela").forEach((s) => s.classList.toggle("ativa", s.id === "tela-" + tela));
  if (tela === "local") desenharLocal();
  if (tela === "fila") desenharFila();
  if (tela === "ajustes" && !ajustesEditados) preencherAjustes();
  if (tela !== "ler" && lendo) fecharCamera();
}

function toast(msg, tipo = "") {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast ver " + tipo;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.className = "toast"), tipo === "erro" ? 8000 : 5000);
}

function avisarLeitura(msg, erro = false) {
  const el = $("#leitura-msg");
  el.textContent = msg;
  el.classList.toggle("erro-txt", erro);
}

function vibrar(p) { try { navigator.vibrate?.(p); } catch {} }

// ------------------------------------------------------------------ câmera
let detector, stream, track, lendo = false;

async function criarDetector() {
  if ("BarcodeDetector" in window) {
    try {
      const f = await BarcodeDetector.getSupportedFormats();
      if (f.includes("qr_code")) return new BarcodeDetector({ formats: ["qr_code"] });
    } catch {}
  }
  // iPhone e navegadores sem leitor nativo: ZXing em WebAssembly (funciona offline)
  const api = window.BarcodeDetectionAPI;
  api.setZXingModuleOverrides({
    locateFile: (arq, pre) => arq.endsWith(".wasm") ? new URL("vendor/zxing_reader.wasm", location.href).href : pre + arq,
  });
  return new api.BarcodeDetector({ formats: ["qr_code"] });
}

async function abrirCamera() {
  if (lendo) return fecharCamera();
  try {
    detector ??= await criarDetector();
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false,
    });
    const v = $("#video");
    v.srcObject = stream; await v.play();
    track = stream.getVideoTracks()[0];
    try { track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }); } catch {}
    $("#btn-lanterna").hidden = !track.getCapabilities?.().torch;
    lendo = true;
    $(".camera").classList.add("lendo");
    $("#btn-camera").textContent = "Fechar câmera";
    avisarLeitura("");
    laco();
  } catch (e) {
    avisarLeitura(e.name === "NotAllowedError" ? "Câmera bloqueada. Permita o acesso nas configurações do navegador ou use Colar texto abaixo." : "Não foi possível abrir a câmera. Tente novamente ou use Colar texto abaixo.", true);
    stream?.getTracks().forEach((t) => t.stop());
    console.error(e);
  }
}

function fecharCamera() {
  lendo = false;
  stream?.getTracks().forEach((t) => t.stop());
  $(".camera").classList.remove("lendo");
  $("#btn-camera").textContent = "Abrir câmera";
  $("#btn-lanterna").hidden = true;
}

let lanterna = false;
$("#btn-lanterna").addEventListener("click", async () => {
  lanterna = !lanterna;
  try { await track.applyConstraints({ advanced: [{ torch: lanterna }] }); $("#btn-lanterna").setAttribute("aria-pressed", String(lanterna)); } catch { lanterna = !lanterna; avisarLeitura("Lanterna indisponível. Procure um local mais iluminado."); }
});

async function laco() {
  const v = $("#video");
  while (lendo) {
    try {
      if (v.readyState >= 2) {
        const codigos = await detector.detect(v);
        for (const c of codigos) await receber(c.rawValue);
      }
    } catch (e) { console.warn(e); }
    await new Promise((r) => setTimeout(r, 120));
  }
}

$("#btn-camera").addEventListener("click", abrirCamera);
document.addEventListener("visibilitychange", () => { if (document.hidden && lendo) fecharCamera(); });

// ------------------------------------------------------------------ montagem do boletim
const vistosRecente = new Map(); // evita reprocessar o mesmo QR a cada quadro

async function receber(texto) {
  const agora = Date.now();
  if (vistosRecente.get(texto) > agora - 4000) return;
  vistosRecente.set(texto, agora);

  const q = identificar(texto);
  if (!q) { avisarLeitura("Este texto não é um QR Code de boletim de urna. Confira o conteúdo colado.", true); return false; }

  // QR do certificado logo após um boletim completo: anexa ao boletim salvo
  if (q.tipo === "QRCE" && regAtual && leitor.completo()) {
    const r = leitor.adicionar(texto);
    if (r === "novo") {
      regAtual.qrcodes = (await leitor.montar()).qrcodes;
      regAtual.certificado = leitor.totalCe !== null && Object.keys(leitor.ce).length === leitor.totalCe;
      if (regAtual.status === "enviado") regAtual.status = "pendente";
      await db.salvar(regAtual);
      vibrar(40); flash(); desenharProgresso();
      desenharUltimo(regAtual); atualizarBadge();
      agendarEnvio();
    }
    if (r === "conflito") { avisarLeitura("Certificado de outra urna. Confira o número da seção na fita.", true); return false; }
    return true;
  }

  // Novo boletim começando enquanto o anterior já está completo
  if (q.tipo === "QRBU" && leitor.completo()) novaUrna();

  const r = leitor.adicionar(texto);
  if (r === "repetido") return true;
  if (r === "conflito") {
    vibrar([80, 60, 80]);
    avisarLeitura("QR de outra urna. Termine esta leitura ou toque em Descartar para começar novamente.", true);
    return false;
  }
  vibrar(40); flash(); desenharProgresso();

  if (leitor.completo()) return concluir();
  return true;
}

async function concluir() {
  try {
    const bu = await leitor.montar();
    const c = bu.cabecalho;
    const existente = await db.obter(c.chave);
    if (existente) {
      toast(`Seção ${c.secao} já tinha sido lida`, "");
      regAtual = existente;
      desenharUltimo(existente);
      return true;
    }
    regAtual = {
      chave: c.chave, bu, qrcodes: bu.qrcodes, certificado: bu.certificadoCompleto,
      status: "pendente", erro: null, lidoEm: new Date().toISOString(), enviadoEm: null,
    };
    delete regAtual.bu.qrcodes;
    await db.salvar(regAtual);
    vibrar([60, 40, 160]);
    toast(`Seção ${c.secao} guardada neste celular`, "ok");
    avisarLeitura("Boletim guardado neste celular. A confirmação da rádio aparece abaixo e na aba Envio.");
    desenharUltimo(regAtual);
    atualizarBadge();
    agendarEnvio();
    return true;
  } catch (e) {
    vibrar([200, 80, 200]);
    avisarLeitura((e instanceof ErroBU ? e.message : "Não foi possível guardar este boletim") + ". Confira os textos ou leia novamente a fita.", true);
    console.error(e);
    novaUrna(); // leitura corrompida: recomeça esta urna
    return false;
  }
}

function novaUrna() {
  leitor = new LeitorBU();
  regAtual = null;
  desenharProgresso();
}

$("#btn-descartar").addEventListener("click", () => {
  if (!leitor.vazio() && !leitor.completo() && !confirm("Descartar os QR Codes desta leitura incompleta? Será preciso lê-los novamente. Os boletins já guardados continuam salvos.")) return;
  novaUrna(); avisarLeitura("Leitura reiniciada. Os boletins já guardados continuam salvos.");
});

$("#btn-manual").addEventListener("click", async () => {
  const campo = $("#txt-manual"), botao = $("#btn-manual"), msg = $("#manual-msg");
  const linhas = campo.value.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  if (!linhas.length) { msg.textContent = "Cole pelo menos um texto de QR Code antes de processar."; campo.focus(); return; }
  botao.disabled = true;
  let falhou = false;
  try {
    for (const l of linhas) {
      vistosRecente.delete(l);
      try { if (await receber(l) === false) falhou = true; }
      catch { falhou = true; avisarLeitura("Não foi possível processar este QR. Confira a fita e tente novamente.", true); }
    }
    msg.textContent = falhou ? "Há textos recusados. O conteúdo foi mantido para você conferir e tentar novamente." : "Textos processados. Confira o progresso da leitura acima.";
    msg.classList.toggle("erro-txt", falhou);
    if (!falhou) campo.value = "";
  } finally { botao.disabled = false; }
});

function flash() {
  const c = $(".camera"); c.classList.remove("flash"); void c.offsetWidth; c.classList.add("flash");
}

function desenharProgresso() {
  const chips = [];
  const total = leitor.totalBu ?? "?";
  const n = leitor.totalBu ?? 3;
  for (let i = 1; i <= n; i++)
    chips.push(`<span class="chip ${leitor.bu[i] ? "ok" : ""}">Boletim ${i}/${total}</span>`);
  const nCe = leitor.totalCe ?? 2;
  for (let i = 1; i <= nCe; i++)
    chips.push(`<span class="chip ${leitor.ce[i] ? "ok" : ""}">Certificado ${i}/${nCe}</span>`);
  $("#chips").innerHTML = chips.join("");
  $("#dica").innerHTML = leitor.completo()
    ? (leitor.totalCe !== null && Object.keys(leitor.ce).length === leitor.totalCe
      ? "Integridade conferida no celular e certificado lido. A rádio verificará a assinatura digital no envio."
      : "Integridade conferida no celular. Leia os 2 QR do <b>certificado</b> para a rádio verificar a assinatura digital da urna.")
    : leitor.vazio() ? "Leia os QR Codes do boletim, em qualquer ordem. O app avisa quando a urna estiver completa."
    : `Faltam: QR ${leitor.faltando().join(", ")} do boletim.`;
}

// Chaves vindas do servidor: '<UE>-<cargo>-<número>', UE = BR (presidente), UF ou código TSE do município
function nomeDe(c, codigoCargo, numero) {
  if (!c) return null;
  const ue = codigoCargo === 1 ? "BR" : codigoCargo >= 11 ? c.municipioTse : c.uf;
  return nomes[`${ue}-${codigoCargo}-${numero}`] || null;
}
const nomeLocal = (c) => nomes[`L-${c.municipioTse}-${c.zona}-${c.local}`] || `local de votação ${c.local}`;
const urnasLocal = (c) => nomes[`LS-${c.municipioTse}-${c.zona}-${c.local}`] || null;
const nomeMunicipio = (c) => nomes[`M-${c.municipioTse}`] || `município ${c.municipioTse}/${c.uf}`;

function desenharUltimo(reg) {
  const { cabecalho: c, cargos } = reg.bu;
  const principal = cargos.find((x) => x.codigo === 1) || cargos.find((x) => x.codigo === 11) || cargos[0];
  const lista = Object.entries(principal.candidatos).sort((a, b) => b[1] - a[1]).slice(0, 4)
    .map(([n, v]) => `<div>${esc(nomeDe(c, principal.codigo, n) || "Nº " + n)}: <b>${fmt(v)}</b> (${pct(v, principal.totais.validos)})</div>`).join("");
  const el = $("#ultimo");
  el.hidden = false;
  el.innerHTML = `
    <p class="secao-tit">Zona ${c.zona} · Seção ${c.secao}</p>
    <div class="dica">${esc(nomeLocal(c))} · ${esc(nomeMunicipio(c))}</div>
    <div class="dica">${c.turno}º turno · ${c.abrangencia} · urna ${c.urna} · ${fmt(c.comparecimento)} de ${fmt(c.aptos)} eleitores</div>
    ${c.oficial ? "" : `<p class="alerta-txt"><b>Atenção:</b> boletim de ${c.fase}, não oficial.</p>`}
    <p style="margin:10px 0 4px"><b>${principal.cargo}</b></p>${lista}
    <div class="dica">Brancos ${principal.totais.BRAN ?? 0} · Nulos ${principal.totais.NULO ?? 0}</div>
    ${cargos.some((x) => x.avisos.length) ? `<p class="erro-txt">Somas internas divergentes: confira o papel.</p>` : ""}
    <p id="ultimo-envio" class="mensagem">${reg.status === "enviado" ? "Recebido pela rádio. " + (reg.assinaturaServidor === "valida" ? "Assinatura digital verificada pelo servidor." : reg.assinaturaServidor === "sem_certificado" ? "Envie também o certificado para verificar a assinatura digital." : "Consulte a situação da assinatura no painel.") : "Guardado neste celular; aguardando envio à rádio."}</p>`;
}

// ------------------------------------------------------------------ subtotal do local
async function desenharLocal() {
  const regs = (await db.todos()).sort((a, b) => a.bu.cabecalho.secao - b.bu.cabecalho.secao);
  const sel = $("#sel-local");
  const locais = [...new Set(regs.map((r) => `${r.bu.cabecalho.zona}/${r.bu.cabecalho.local}`))];
  const atual = sel.value;
  sel.innerHTML = `<option value="">Todos os boletins deste celular (${regs.length})</option>` +
    locais.map((l) => {
      const doLocal = regs.filter((r) => `${r.bu.cabecalho.zona}/${r.bu.cabecalho.local}` === l);
      const c = doLocal[0].bu.cabecalho;
      const esperadas = urnasLocal(c);
      const qtd = esperadas ? `${doLocal.length} de ${esperadas} urnas` : `${doLocal.length} urnas`;
      return `<option value="${esc(l)}">${esc(nomeLocal(c))} · zona ${esc(c.zona)} (${qtd})</option>`;
    }).join("");
  sel.value = locais.includes(atual) ? atual : (locais.length === 1 ? locais[0] : "");

  const filtro = sel.value;
  const escolhidos = regs.filter((r) => !filtro || `${r.bu.cabecalho.zona}/${r.bu.cabecalho.local}` === filtro);
  const s = somar(escolhidos.map((r) => r.bu));
  const cab = escolhidos[0]?.bu.cabecalho;

  const esperadas = filtro && cab ? urnasLocal(cab) : null;
  $("#resumo-local").innerHTML = `
    <div><b>${s.secoes}${esperadas ? `<small style="font-size:14px"> de ${esperadas}</small>` : ""}</b><span>urnas lidas</span></div>
    <div><b>${fmt(s.comparecimento)}</b><span>votaram</span></div>
    <div><b>${pct(s.comparecimento, s.aptos)}</b><span>comparecimento</span></div>`;

  if (!s.secoes) { $("#cargos-local").innerHTML = `<p class="dica" style="text-align:center">Nenhum boletim lido ainda.</p>`; return; }

  $("#cargos-local").innerHTML = s.cargos.map((cg) => {
    const ordem = Object.entries(cg.candidatos).sort((a, b) => b[1] - a[1]);
    const base = cg.validos;
    const linhas = (lista) => lista.map(([n, v], i) => `
      <div class="cand ${i === 0 ? "lider" : ""}">
        <span class="nome">${esc(nomeDe(cab, cg.codigo, n) || "Nº " + n)} <span class="num">${nomeDe(cab, cg.codigo, n) ? n : ""}</span></span>
        <span class="pct">${pct(v, base)}</span>
        <span class="trilho"><i style="width:${base ? (100 * v / base).toFixed(1) : 0}%"></i></span>
        <span class="votos">${fmt(v)} votos</span>
      </div>`).join("");
    const limite = cg.tipo === "proporcional" ? 10 : 12;
    const nota = cg.codigo === 5 ? " · cada eleitor votou em 2" : cg.tipo === "proporcional" ? " · inclui votos de legenda nos válidos" : "";
    return `<div class="cartao cargo">
      <h3>${cg.cargo}</h3>
      <div class="sub">Válidos ${fmt(base)} · Brancos ${fmt(cg.BRAN)} · Nulos ${fmt(cg.NULO)}${nota}</div>
      ${linhas(ordem.slice(0, limite))}
      ${ordem.length > limite ? `<details class="mais"><summary>Ver todos (${ordem.length})</summary>${linhas(ordem.slice(limite))}</details>` : ""}
    </div>`;
  }).join("");
}
$("#sel-local").addEventListener("change", desenharLocal);

// ------------------------------------------------------------------ envio
let enviando = false, timerEnvio, acessoRecusado = false;
let situacaoRadio = "nao_testado", progressoEnvio = "";

async function requisitar(caminho, cfg, opcoes = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    return await fetch(new URL(caminho, cfg.servidor), {
      ...opcoes, signal: controller.signal,
      headers: { ...opcoes.headers, Authorization: `Token ${cfg.token}` },
    });
  } finally { clearTimeout(timeout); }
}

function agendarEnvio() {
  clearTimeout(timerEnvio);
  if (ajustes.ler().envio !== "imediato") return;
  timerEnvio = setTimeout(() => enviarPendentes(), 5000);
}

async function enviarPendentes(manual = false) {
  const cfg = ajustes.ler();
  // Um único ponto protege todos os gatilhos: leitura, inicialização, ajustes e reconexão.
  if ((!manual && cfg.envio !== "imediato") || (!manual && acessoRecusado) || enviando) return;
  if (!cfg.servidor || !cfg.token) {
    estadoRede();
    if (manual) { mostrar("ajustes"); $("#ajustes-msg").textContent = "Informe o endereço e o código fornecidos pela rádio, ou use o QR Code de configuração."; }
    return;
  }
  const regs = (await db.todos()).filter((r) => manual ? r.status !== "enviado" : r.status === "pendente");
  if (enviando) return;
  if (!regs.length) { if (manual) toast("Todos os boletins deste celular já foram recebidos pela rádio."); return; }
  enviando = true;
  $("#btn-enviar").disabled = true;
  $("#btn-enviar").textContent = "Enviando…";
  $("#tela-fila").setAttribute("aria-busy", "true");
  let ok = 0, falha = 0, processados = 0;
  try {
    for (const r of regs) {
      // Uma troca para envio manual ou exclusão não deve disparar o restante da fila.
      if (!manual && ajustes.ler().envio !== "imediato") break;
      progressoEnvio = `Enviando ${++processados} de ${regs.length} boletins à rádio…`;
      estadoRede();
      let interromper = false;
      try {
        const resp = await requisitar("/api/boletins/", cfg, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chave: r.chave, qrcodes: r.qrcodes, lido_em: r.lidoEm, reporter: cfg.reporter }),
        });
        if (resp.ok) {
          const dados = await resp.json();
          situacaoRadio = "conectado"; acessoRecusado = false;
          r.status = "enviado"; r.erro = null; r.enviadoEm = new Date().toISOString();
          r.assinaturaServidor = dados.assinatura;
          ok++;
        } else if (resp.status === 401 || resp.status === 403) {
          situacaoRadio = "recusado"; acessoRecusado = true;
          r.erro = "Código de acesso recusado. Corrija o código em Ajustes e teste a conexão.";
          falha++; interromper = true;
        } else if (resp.status >= 400 && resp.status < 500) {
          situacaoRadio = "conectado";
          r.status = "erro"; r.erro = (await resp.json().catch(() => ({}))).detail || "Boletim recusado. Confira a fita e tente novamente.";
          falha++;
        } else {
          situacaoRadio = "indisponivel"; r.erro = "A rádio está indisponível. O boletim continua guardado neste celular.";
          falha++; interromper = true;
        }
      } catch {
        situacaoRadio = "indisponivel"; r.erro = "Sem resposta da rádio. Confira a internet; o boletim continua guardado neste celular.";
        falha++; interromper = true;
      }
      const atual = await db.obter(r.chave);
      if (atual) {
        // Um certificado lido durante o POST precisa de uma nova confirmação do servidor.
        if (JSON.stringify(atual.qrcodes) === JSON.stringify(r.qrcodes)) await db.salvar(r);
        else { atual.status = "pendente"; atual.erro = r.erro; await db.salvar(atual); }
        if (regAtual?.chave === r.chave) regAtual = await db.obter(r.chave);
      }
      if (interromper) break;
    }
  } finally {
    enviando = false; progressoEnvio = "";
    $("#btn-enviar").disabled = false; $("#btn-enviar").textContent = "Enviar pendentes";
    $("#tela-fila").removeAttribute("aria-busy");
    await atualizarBadge();
    if (regAtual) desenharUltimo(regAtual);
    if ($("#tela-fila").classList.contains("ativa")) await desenharFila();
  }
  if (ok) toast(`${ok} ${ok === 1 ? "boletim recebido" : "boletins recebidos"} pela rádio`, "ok");
  if (manual && falha) toast(acessoRecusado ? "Código recusado. Corrija o acesso em Ajustes." : "Há boletins aguardando envio. Confira a situação na lista.", "erro");
  if (ok) baixarNomes();
}

$("#btn-enviar").addEventListener("click", () => enviarPendentes(true));
$("#btn-corrigir").addEventListener("click", () => { mostrar("ajustes"); $("#form-ajustes").elements.token.focus(); });
window.addEventListener("online", () => { situacaoRadio = "nao_testado"; estadoRede(); enviarPendentes(); });
window.addEventListener("offline", estadoRede);
setInterval(() => { if (navigator.onLine) enviarPendentes(); }, 30000);

async function atualizarBadge() {
  const n = (await db.todos()).filter((r) => r.status !== "enviado").length;
  const b = $("#badge"); b.hidden = !n; b.textContent = n;
  b.setAttribute("aria-label", `${n} boletins aguardando envio`);
  estadoRede();
}

function estadoRede() {
  const el = $("#rede"), cfg = ajustes.ler();
  const modoManual = cfg.envio === "manual";
  const modo = modoManual ? "Envio manual: toque em Enviar pendentes quando quiser enviar." : "Envio automático: a rádio receberá os boletins quando houver conexão.";
  let selo = "verificar acesso", mensagem = "Teste a conexão em Ajustes para confirmar o acesso à rádio.", classe = "";
  if (!navigator.onLine) { selo = "sem internet"; classe = "off"; mensagem = "Sem internet. Seus boletins continuam guardados neste celular."; }
  else if (!cfg.servidor || !cfg.token) { selo = "configurar rádio"; mensagem = "Configure este celular com o QR Code fornecido pela rádio ou preencha os Ajustes."; }
  else if (acessoRecusado) { selo = "acesso recusado"; classe = "off"; mensagem = "A rádio recusou o código de acesso. Corrija em Ajustes. Seus boletins continuam guardados."; }
  else if (enviando) { selo = "enviando"; mensagem = progressoEnvio; }
  else if (situacaoRadio === "indisponivel") { selo = "rádio sem resposta"; classe = "off"; mensagem = "A rádio não respondeu. Seus boletins continuam guardados. Confira a internet e teste a conexão em Ajustes."; }
  else if (situacaoRadio === "conectado") { selo = "acesso confirmado"; classe = "on"; mensagem = "Acesso à rádio confirmado. Confira em Envio quais boletins já foram recebidos."; }
  el.textContent = selo; el.className = "rede" + (classe ? " " + classe : "");
  $("#envio-msg").textContent = mensagem;
  $("#btn-corrigir").hidden = !acessoRecusado;
  $("#fila-dica").textContent = modo;
}

async function desenharFila() {
  const regs = (await db.todos()).sort((a, b) => b.lidoEm.localeCompare(a.lidoEm));
  const pend = regs.filter((r) => r.status !== "enviado").length;
  $("#fila-resumo").textContent = `${regs.length - pend} enviados · ${pend} pendentes`;
  $("#lista-fila").innerHTML = regs.map((r) => {
    const c = r.bu.cabecalho;
    const hora = new Date(r.lidoEm).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    return `<li><div><b>Zona ${esc(c.zona)} · Seção ${esc(c.secao)}</b>
      <small>lida às ${hora} · local ${esc(c.local)}${r.certificado ? " · com certificado" : ""}${r.erro ? " · " + esc(r.erro) : ""}</small></div>
      <span class="status ${r.status}">${{ enviado: "recebido pela rádio", pendente: "aguardando envio", erro: "recusado" }[r.status]}</span></li>`;
  }).join("") || `<p class="dica" style="text-align:center">Nenhum boletim lido ainda.</p>`;
}

$("#btn-exportar").addEventListener("click", async () => {
  const regs = await db.todos();
  if (!regs.length) return toast("Nada para salvar ainda");
  const cfg = ajustes.ler();
  const dados = { formato: "apura-bu/1", gerado_em: new Date().toISOString(), reporter: cfg.reporter,
    boletins: regs.map((r) => ({ chave: r.chave, qrcodes: r.qrcodes, lido_em: r.lidoEm })) };
  const blob = new Blob([JSON.stringify(dados, null, 1)], { type: "application/json" });
  const nome = `boletins-${(cfg.reporter || "celular").replace(/\W+/g, "-")}-${new Date().toISOString().slice(0, 16).replace(/\D/g, "")}.json`;
  const arq = new File([blob], nome, { type: "application/json" });
  try {
    if (navigator.canShare?.({ files: [arq] })) { await navigator.share({ files: [arq], title: "Boletins lidos" }); return; }
  } catch (e) { if (e.name === "AbortError") return; }
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: nome });
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
});

// ------------------------------------------------------------------ nomes dos candidatos (vindos do servidor)
function carregarNomes() { try { return JSON.parse(localStorage.getItem("apura-nomes") || "{}"); } catch { return {}; } }

async function baixarNomes() {
  const cfg = ajustes.ler();
  if (!cfg.servidor) return;
  try {
    const r = await fetch(new URL("/api/nomes/", cfg.servidor), { headers: { Authorization: `Token ${cfg.token}` } });
    if (r.ok) { nomes = await r.json(); try { localStorage.setItem("apura-nomes", JSON.stringify(nomes)); } catch {} }
  } catch {}
}

// ------------------------------------------------------------------ ajustes
let ajustesEditados = false;
$("#form-ajustes").addEventListener("input", () => { ajustesEditados = true; });
function preencherAjustes() {
  const cfg = ajustes.ler(), f = $("#form-ajustes");
  for (const k of Object.keys(cfg)) if (f.elements[k]) f.elements[k].value = cfg[k];
}

$("#form-ajustes").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const cfg = Object.fromEntries(f.entries());
  cfg.servidor = cfg.servidor.trim().replace(/\/+$/, ""); cfg.token = cfg.token.trim();
  ajustes.gravar(cfg); ajustesEditados = false;
  acessoRecusado = false; situacaoRadio = "nao_testado";
  clearTimeout(timerEnvio);
  estadoRede();
  $("#ajustes-msg").className = "mensagem";
  $("#ajustes-msg").textContent = cfg.envio === "manual" ? "Ajustes salvos. O envio será feito somente pelo botão Enviar pendentes." : "Ajustes salvos. Teste a conexão para confirmar o acesso à rádio.";
  enviarPendentes(); baixarNomes();
});

$("#btn-testar").addEventListener("click", async () => {
  const f = $("#form-ajustes"), msg = $("#ajustes-msg"), botao = $("#btn-testar");
  const cfg = { servidor: f.elements.servidor.value.trim(), token: f.elements.token.value.trim() };
  if (!cfg.servidor || !cfg.token) { msg.textContent = "Informe o endereço e o código de acesso fornecidos pela rádio."; return; }
  botao.disabled = true; botao.textContent = "Testando…";
  msg.textContent = "Testando o acesso à rádio…"; msg.className = "mensagem";
  try {
    const r = await requisitar("/api/ping/", cfg);
    const recusado = r.status === 401 || r.status === 403;
    msg.textContent = r.ok ? "Acesso à rádio confirmado." + (ajustesEditados ? " Salve os ajustes para usar estes dados no envio." : "")
      : recusado ? "Código recusado. Confira o código com a coordenação, corrija e salve os ajustes." : "A rádio respondeu com erro. Tente novamente em alguns instantes.";
    msg.classList.add(r.ok ? "ok-txt" : "erro-txt");
    const salvo = ajustes.ler();
    if (cfg.servidor.replace(/\/+$/, "") === salvo.servidor && cfg.token === salvo.token) {
      acessoRecusado = recusado; situacaoRadio = r.ok ? "conectado" : recusado ? "recusado" : "indisponivel";
      estadoRede();
    }
  } catch {
    msg.textContent = "A rádio não respondeu. Confira o endereço e sua internet, depois tente novamente."; msg.classList.add("erro-txt");
    const salvo = ajustes.ler();
    if (cfg.servidor.replace(/\/+$/, "") === salvo.servidor && cfg.token === salvo.token) {
      situacaoRadio = "indisponivel"; estadoRede();
    }
  }
  finally { botao.disabled = false; botao.textContent = "Testar conexão"; }
});

$("#btn-limpar").addEventListener("click", async () => {
  if (enviando) { toast("Aguarde o envio terminar antes de apagar os boletins."); return; }
  const pend = (await db.todos()).filter((r) => r.status !== "enviado").length;
  const aviso = pend ? `Há ${pend} boletim(ns) ainda NÃO enviado(s). ` : "";
  if (!confirm(aviso + "Apagar todos os boletins guardados neste celular?")) return;
  await db.limpar(); novaUrna(); $("#ultimo").hidden = true; atualizarBadge(); toast("Boletins apagados");
});

// ------------------------------------------------------------------ início
// Configuração automática: a rádio mostra um QR Code com o link /app/#cfg=<dados>
(function configurarPeloLink() {
  const m = location.hash.match(/cfg=([\w-]+)/);
  const cfg = ajustes.ler();
  if (m) {
    try {
      const b64 = m[1].replace(/-/g, "+").replace(/_/g, "/");
      const dados = JSON.parse(atob(b64 + "=".repeat((4 - b64.length % 4) % 4)));
      const servidor = dados.servidor ? new URL(dados.servidor).origin : cfg.servidor;
      // O QR da rádio sempre aponta para o próprio servidor. Outro endereço pode ser um link falso
      // que desvia os boletins; trocar uma configuração já existente também pede confirmação.
      const outroServidor = dados.servidor && servidor !== location.origin;
      const trocaConfig = cfg.token && (servidor !== cfg.servidor || (dados.token && dados.token !== cfg.token));
      const aviso = outroServidor
        ? `Atenção: este link manda os boletins para ${new URL(servidor).host}, que não é o endereço deste app (${location.host}).\n\nSó continue se a coordenação da rádio confirmou este endereço.`
        : `Este link troca a configuração atual deste celular (${cfg.reporter || "sem nome"}) por ${dados.reporter || "outra"}.`;
      if ((outroServidor || trocaConfig) && !confirm(aviso + "\n\nAplicar a nova configuração?")) {
        setTimeout(() => toast("Configuração mantida", "ok"), 300);
      } else {
        ajustes.gravar({ ...cfg, servidor, token: dados.token || cfg.token, reporter: dados.reporter || cfg.reporter });
        setTimeout(() => toast(`Celular configurado: ${dados.reporter || "ok"}`, "ok"), 300);
      }
    } catch { setTimeout(() => toast("Link de configuração inválido", "erro"), 300); }
    history.replaceState(null, "", location.pathname);
  } else if (!cfg.servidor && location.pathname.startsWith("/app/") && location.protocol === "https:") {
    ajustes.gravar({ ...cfg, servidor: location.origin }); // aberto direto do servidor da rádio
  }
})();

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
desenharProgresso(); atualizarBadge(); estadoRede();
if (navigator.onLine) { enviarPendentes(); baixarNomes(); }
