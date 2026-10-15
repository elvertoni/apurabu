// Armazenamento local (IndexedDB): boletins lidos neste celular + fila de envio.
const NOME = "apura-bu", VERSAO = 1;
let _db;

function abrir() {
  if (_db) return Promise.resolve(_db);
  return new Promise((ok, erro) => {
    const r = indexedDB.open(NOME, VERSAO);
    r.onupgradeneeded = () => {
      const s = r.result.createObjectStore("boletins", { keyPath: "chave" });
      s.createIndex("status", "status");
    };
    r.onsuccess = () => ok((_db = r.result));
    r.onerror = () => erro(r.error);
  });
}

function tx(modo, fn) {
  return abrir().then((db) => new Promise((ok, erro) => {
    const t = db.transaction("boletins", modo);
    const req = fn(t.objectStore("boletins"));
    t.oncomplete = () => ok(req.result);
    t.onerror = () => erro(t.error);
  }));
}

export const db = {
  salvar: (reg) => tx("readwrite", (s) => s.put(reg)),
  obter: (chave) => tx("readonly", (s) => s.get(chave)),
  todos: () => tx("readonly", (s) => s.getAll()),
  apagar: (chave) => tx("readwrite", (s) => s.delete(chave)),
  limpar: () => tx("readwrite", (s) => s.clear()),
};

// Ajustes simples (localStorage pode falhar em modo privado)
const PADRAO = { servidor: "", token: "", reporter: "", envio: "imediato" };
export const ajustes = {
  ler() {
    try { return { ...PADRAO, ...JSON.parse(localStorage.getItem("apura-ajustes") || "{}") }; }
    catch { return { ...PADRAO }; }
  },
  gravar(v) { try { localStorage.setItem("apura-ajustes", JSON.stringify(v)); } catch {} },
};
