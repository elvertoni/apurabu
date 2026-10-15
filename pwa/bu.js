// Decodificador do QR Code do Boletim de Urna (TSE) — versão JavaScript.
// Espelha bu_qrcode.py. Roda no navegador (crypto.subtle) e no Node 20+.
// A assinatura digital (ECDSA P-521) é conferida no servidor; aqui validamos
// a cadeia de hashes SHA-512, que já barra QR mal lido, adulterado ou misturado.

export const CARGOS = {
  1: "Presidente", 3: "Governador", 5: "Senador", 6: "Deputado Federal",
  7: "Deputado Estadual", 8: "Deputado Distrital", 9: "Conselheiro Distrital",
  11: "Prefeito", 13: "Vereador",
};
// Ordem de exibição no app (presidente primeiro, como a rádio anuncia)
export const ORDEM_CARGOS = [1, 3, 5, 6, 7, 8, 11, 13, 9];
const TIPO = { 0: "majoritario", 1: "proporcional", 2: "consulta" };
const MUNICIPAIS = new Set([11, 13]);
const TOTAIS = new Set(["APTA", "APTS", "APTT", "NOMI", "LEGC", "BRAN", "NULO", "TOTC"]);
const RE_CAB = /^(QRBU|QRCE):(\d+):(\d+) /;

export class ErroBU extends Error {}

async function sha512Hex(texto) {
  const buf = await crypto.subtle.digest("SHA-512", new TextEncoder().encode(texto));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").toUpperCase();
}

/** Identifica um texto lido pela câmera. */
export function identificar(texto) {
  const t = texto.trim();
  const m = RE_CAB.exec(t);
  if (!m) return null;
  return { tipo: m[1], n: +m[2], total: +m[3], texto: t };
}

/** Junta os QRs de UM boletim (em qualquer ordem). */
export class LeitorBU {
  constructor() { this.bu = {}; this.totalBu = null; this.ce = {}; this.totalCe = null; }

  /** Retorna 'novo' | 'repetido' | 'conflito' (QR de outro boletim na mesma posição). */
  adicionar(texto) {
    const q = identificar(texto);
    if (!q) throw new ErroBU("Este QR Code não é de Boletim de Urna");
    if (q.tipo === "QRBU") {
      if (this.totalBu !== null && this.totalBu !== q.total) return "conflito";
      if (this.bu[q.n] === q.texto) return "repetido";
      if (this.bu[q.n]) return "conflito";
      this.totalBu = q.total; this.bu[q.n] = q.texto;
    } else {
      // certificado: só aceita se for da mesma urna do QR 1
      const idue = (q.texto.match(/IDUE:(\d+)/) || [])[1];
      const idueBu = this.bu[1] && (this.bu[1].match(/IDUE:(\d+)/) || [])[1];
      if (idueBu && idue !== idueBu) return "conflito";
      if (this.ce[q.n] === q.texto) return "repetido";
      this.totalCe = q.total; this.ce[q.n] = q.texto;
    }
    return "novo";
  }

  lidos() { return Object.keys(this.bu).length; }
  faltando() {
    if (this.totalBu === null) return ["1"];
    const f = [];
    for (let i = 1; i <= this.totalBu; i++) if (!this.bu[i]) f.push(String(i));
    return f;
  }
  completo() { return this.totalBu !== null && this.faltando().length === 0; }
  vazio() { return this.lidos() === 0 && Object.keys(this.ce).length === 0; }

  _partes() {
    const res = [];
    for (let i = 1; i <= this.totalBu; i++) {
      let corpo = this.bu[i].replace(/^QRBU:\d+:\d+ VRQR:\S+ (VRCH:\S+ )?/, "").split(" ASSI:")[0];
      const k = corpo.indexOf("HASH:");
      if (k < 0) throw new ErroBU(`QR ${i} sem HASH`);
      res.push([corpo.slice(0, k), corpo.slice(k + 5).split(/\s/)[0].toUpperCase()]);
    }
    return res;
  }

  async validarHashes() {
    let acumulado = "";
    for (const [i, [dados, h]] of this._partes().entries()) {
      const calc = await sha512Hex(acumulado + dados.trimEnd());
      if (calc !== h) throw new ErroBU(`HASH inválido no QR ${i + 1}: leitura com erro, adulterado ou de outro boletim`);
      acumulado += dados + "HASH:" + h + " ";
    }
    return true;
  }

  /** Valida e devolve { cabecalho, cargos, qrcodes }. */
  async montar() {
    if (!this.completo()) throw new ErroBU("Faltam QR Codes: " + this.faltando().join(", "));
    await this.validarHashes();
    const dados = this._partes().map(([d]) => d.trimEnd()).join(" ");
    const bu = interpretar(dados);
    bu.qrcodes = [
      ...Object.keys(this.bu).sort((a, b) => a - b).map((k) => this.bu[k]),
      ...Object.keys(this.ce).sort((a, b) => a - b).map((k) => this.ce[k]),
    ];
    bu.certificadoCompleto = this.totalCe !== null && Object.keys(this.ce).length === this.totalCe;
    return bu;
  }
}

export function interpretar(dados) {
  const cab = {};
  const cargos = [];
  let idel = null, cargo = null, partido = null;

  for (const tok of dados.split(/\s+/)) {
    const i = tok.indexOf(":");
    if (i < 0) continue;
    const k = tok.slice(0, i), v = tok.slice(i + 1);
    if (k === "IDEL") { idel = +v; continue; }
    if (k === "CARG") {
      cargo = { idel, codigo: +v, cargo: CARGOS[+v] || `Cargo ${v}`, candidatos: {}, partidos: {}, totais: {} };
      cargos.push(cargo); partido = null; continue;
    }
    if (!cargo) { cab[k] = v; continue; }
    if (k === "TIPO") cargo.tipo = TIPO[+v] ?? v;
    else if (k === "VERC") cargo.versaoCandidatos = v;
    else if (k === "PART") { partido = { legenda: 0, total: 0 }; cargo.partidos[+v] = partido; }
    else if (k === "LEGP") partido.legenda = +v;
    else if (k === "TOTP") partido.total = +v;
    else if (TOTAIS.has(k)) cargo.totais[k] = +v;
    else if (/^\d+$/.test(k)) cargo.candidatos[+k] = +v;
  }

  for (const c of cargos) conferir(c);
  const codigos = cargos.map((c) => c.codigo);
  const cabecalho = {
    fase: { O: "oficial", S: "simulado", T: "treinamento" }[cab.FASE] || cab.FASE,
    oficial: cab.FASE === "O" && cab.ORLC === "LEG",
    pleito: cab.PLEI, turno: +cab.TURN, dataPleito: cab.DTPL,
    uf: cab.UNFE, municipioTse: cab.MUNI, zona: +cab.ZONA, secao: +cab.SECA,
    local: cab.LOCA, urna: cab.IDUE,
    aptos: +cab.APTO, comparecimento: +cab.COMP, faltosos: +cab.FALT,
    fechamento: `${cab.DTFC} ${cab.HRFC}`,
    abrangencia: codigos.length && codigos.every((c) => MUNICIPAIS.has(c)) ? "municipal" : "geral",
  };
  cabecalho.chave = [cabecalho.pleito, cabecalho.turno, cabecalho.uf, cabecalho.municipioTse, cabecalho.zona, cabecalho.secao].join("-");
  return { cabecalho, cargos };
}

function conferir(c) {
  const t = c.totais;
  const avisos = [];
  const nominal = Object.values(c.candidatos).reduce((a, b) => a + b, 0);
  if ("NOMI" in t && nominal !== t.NOMI) avisos.push(`soma nominal ${nominal} ≠ NOMI ${t.NOMI}`);
  if (["NOMI", "BRAN", "NULO", "TOTC"].every((k) => k in t) && t.NOMI + (t.LEGC || 0) + t.BRAN + t.NULO !== t.TOTC)
    avisos.push("NOMI+LEGC+BRAN+NULO ≠ TOTC");
  for (const [num, p] of Object.entries(c.partidos)) {
    const nom = Object.entries(c.candidatos).filter(([k]) => k.startsWith(num)).reduce((a, [, v]) => a + v, 0);
    if (nom + p.legenda !== p.total) avisos.push(`partido ${num}: nominais+legenda ≠ TOTP`);
  }
  t.validos = (t.NOMI || 0) + (t.LEGC || 0);
  c.avisos = avisos;
}

/** Soma vários BUs (subtotal do local ou geral). Ignora seções repetidas. */
export function somar(bus) {
  const vistos = new Set();
  const porCargo = {};
  let secoes = 0, aptos = 0, comparecimento = 0;
  for (const bu of bus) {
    if (vistos.has(bu.cabecalho.chave)) continue;
    vistos.add(bu.cabecalho.chave);
    secoes++; aptos += bu.cabecalho.aptos; comparecimento += bu.cabecalho.comparecimento;
    for (const c of bu.cargos) {
      const s = (porCargo[c.codigo] ??= { codigo: c.codigo, cargo: c.cargo, tipo: c.tipo, candidatos: {}, partidos: {}, BRAN: 0, NULO: 0, LEGC: 0, validos: 0, TOTC: 0 });
      for (const [n, v] of Object.entries(c.candidatos)) s.candidatos[n] = (s.candidatos[n] || 0) + v;
      for (const [n, p] of Object.entries(c.partidos)) s.partidos[n] = (s.partidos[n] || 0) + p.total;
      for (const k of ["BRAN", "NULO", "LEGC", "validos", "TOTC"]) s[k] += c.totais[k] || 0;
    }
  }
  const cargos = ORDEM_CARGOS.filter((c) => porCargo[c]).map((c) => porCargo[c]);
  return { secoes, aptos, comparecimento, cargos };
}
