"""
Decodificador do QR Code do Boletim de Urna (BU) — TSE.

Etapa 1 do projeto de apuração extraoficial para rádio.

Formato validado com BUs reais do 1º turno de 2026 (VRQR 6.0):
  - Um BU é impresso em N QR Codes "QRBU:n:N" + 2 QR Codes "QRCE:n:2" (certificado da urna).
  - Os registros são pares CHAVE:VALOR separados por espaço e podem
    continuar de um QR para o seguinte (ex.: um partido começa no QR 1 e termina no QR 2).
  - Integridade: HASH de cada QR = SHA-512 do conteúdo acumulado dos QRs anteriores
    ("<dados> HASH:<hash> ...") + dados do QR atual (sem o espaço final).
  - Autenticidade: ASSI (último QR) = assinatura ECDSA P-521/SHA-512 sobre os bytes
    do último HASH, verificável com o certificado X.509 impresso nos QRCE.

Uso:
    leitor = LeitorBU()
    for texto in textos_lidos_pela_camera:
        status = leitor.adicionar(texto)      # aceita os QRs em qualquer ordem
    if leitor.completo():
        bu = leitor.montar()                  # dict com cabeçalho, cargos e votos
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- tabelas TSE

CARGOS = {
    1: "Presidente",
    3: "Governador",
    5: "Senador",
    6: "Deputado Federal",
    7: "Deputado Estadual",
    8: "Deputado Distrital",
    9: "Conselheiro Distrital",
    11: "Prefeito",
    13: "Vereador",
}
TIPO_CARGO = {0: "majoritario", 1: "proporcional", 2: "consulta"}
FASES = {"O": "oficial", "S": "simulado", "T": "treinamento"}
ORIGENS = {"VOTA": "Software de Votação", "RED": "Recuperador de Dados", "SA": "Sistema de Apuração"}
CARGOS_MUNICIPAIS = {11, 13}

# Campos que encerram o bloco de um cargo (totais do cargo)
TOTAIS_CARGO = {"APTA", "APTS", "APTT", "NOMI", "LEGC", "BRAN", "NULO", "TOTC"}

_RE_CAB = re.compile(r"^(QRBU|QRCE):(\d+):(\d+) ")


class ErroBU(Exception):
    pass


# ---------------------------------------------------------------- leitura dos QRs


@dataclass
class LeitorBU:
    """Junta os QR Codes de UM boletim, em qualquer ordem, e valida a integridade."""

    partes_bu: dict[int, str] = field(default_factory=dict)
    total_bu: int | None = None
    partes_ce: dict[int, str] = field(default_factory=dict)
    total_ce: int | None = None

    def adicionar(self, texto: str) -> str:
        texto = texto.strip()
        m = _RE_CAB.match(texto)
        if not m:
            raise ErroBU("QR Code não é de Boletim de Urna")
        tipo, n, total = m.group(1), int(m.group(2)), int(m.group(3))
        if tipo == "QRBU":
            if self.total_bu not in (None, total):
                raise ErroBU("QR de outro boletim (total de partes diferente)")
            # a identidade do boletim é garantida pelo hash encadeado em validar_hashes()
            self.total_bu = total
            self.partes_bu[n] = texto
        else:
            self.total_ce = total
            self.partes_ce[n] = texto
        return self.status()

    def faltando(self) -> list[str]:
        f = []
        if self.total_bu is None:
            f.append("QRBU 1")
        else:
            f += [f"QRBU {i}/{self.total_bu}" for i in range(1, self.total_bu + 1) if i not in self.partes_bu]
        return f

    def completo(self) -> bool:
        return self.total_bu is not None and not self.faltando()

    def status(self) -> str:
        if self.completo():
            return "completo"
        return "faltam: " + ", ".join(self.faltando())

    # ------------------------------------------------------------ integridade

    def _dados_e_hashes(self) -> list[tuple[str, str]]:
        res = []
        for i in range(1, self.total_bu + 1):
            t = self.partes_bu[i]
            corpo = re.sub(r"^QRBU:\d+:\d+ VRQR:\S+ (VRCH:\S+ )?", "", t)
            corpo = corpo.split(" ASSI:")[0]
            if "HASH:" not in corpo:
                raise ErroBU(f"QR {i} sem HASH")
            dados, h = corpo.split("HASH:", 1)
            res.append((dados, h.split()[0].upper()))
        return res

    def validar_hashes(self) -> bool:
        acumulado = ""
        for i, (dados, h) in enumerate(self._dados_e_hashes(), 1):
            calc = hashlib.sha512((acumulado + dados.rstrip()).encode("ascii")).hexdigest().upper()
            if calc != h:
                raise ErroBU(f"HASH inválido no QR {i}: QR adulterado, mal lido ou de outro boletim")
            acumulado += dados + "HASH:" + h + " "
        return True

    def certificado_der(self) -> bytes | None:
        if self.total_ce is None or len(self.partes_ce) < self.total_ce:
            return None
        hexa = "".join(self.partes_ce[i].split("CERT:")[1].split()[0] for i in sorted(self.partes_ce))
        der = bytes.fromhex(hexa)
        # comprimento DER (SEQUENCE 30 82 LL LL) — descarta bytes de preenchimento
        if der[:2] == b"\x30\x82":
            der = der[: 4 + int.from_bytes(der[2:4], "big")]
        return der

    def validar_assinatura(self) -> str:
        """Retorna 'valida', 'sem_certificado' ou levanta ErroBU."""
        der = self.certificado_der()
        if der is None:
            return "sem_certificado"
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        cert = x509.load_der_x509_certificate(der)
        if "AC URNA" not in cert.issuer.rfc4514_string():
            raise ErroBU("Certificado não emitido pela AC URNA do TSE")
        ultimo = self.partes_bu[self.total_bu]
        if "ASSI:" not in ultimo:
            raise ErroBU("Último QR sem assinatura")
        assinatura = bytes.fromhex(ultimo.split("ASSI:")[1].split()[0])
        ultimo_hash = bytes.fromhex(self._dados_e_hashes()[-1][1])
        try:
            cert.public_key().verify(assinatura, ultimo_hash, ec.ECDSA(hashes.SHA512()))
        except InvalidSignature:
            raise ErroBU("Assinatura digital inválida")
        return "valida"

    # ------------------------------------------------------------ montagem

    def montar(self) -> dict:
        if not self.completo():
            raise ErroBU(self.status())
        self.validar_hashes()
        dados = " ".join(d.rstrip() for d, _ in self._dados_e_hashes())
        bu = interpretar(dados)
        bu["integridade"] = {"hash": "valido", "assinatura": self.validar_assinatura()}
        return bu


# ---------------------------------------------------------------- interpretação


def _tokens(dados: str):
    for tok in dados.split():
        if ":" in tok:
            k, v = tok.split(":", 1)
            yield k, v


def interpretar(dados: str) -> dict:
    """Converte a sequência CHAVE:VALOR (já unida e validada) em estrutura."""
    cab: dict = {}
    eleicoes: list[dict] = []
    idel_atual = None
    cargo = None
    partido = None

    for k, v in _tokens(dados):
        if k == "IDEL":
            idel_atual = int(v)
            continue
        if k == "CARG":
            cargo = {
                "idel": idel_atual,
                "codigo": int(v),
                "cargo": CARGOS.get(int(v), f"Cargo {v}"),
                "candidatos": {},
                "partidos": {},
                "totais": {},
            }
            eleicoes.append(cargo)
            partido = None
            continue
        if cargo is None:  # ainda no cabeçalho
            cab[k] = v
            continue
        if k == "TIPO":
            cargo["tipo"] = TIPO_CARGO.get(int(v), v)
        elif k == "VERC":
            cargo["versao_candidatos"] = v
        elif k == "PART":
            partido = {"legenda": 0, "total": 0}
            cargo["partidos"][int(v)] = partido
        elif k == "LEGP":
            partido["legenda"] = int(v)
        elif k == "TOTP":
            partido["total"] = int(v)
        elif k in TOTAIS_CARGO:
            cargo["totais"][k] = int(v)
        elif k.isdigit():
            cargo["candidatos"][int(k)] = int(v)
        else:
            cargo.setdefault("outros", {})[k] = v

    cabecalho = {
        "origem": ORIGENS.get(cab.get("ORIG"), cab.get("ORIG")),
        "fase": FASES.get(cab.get("FASE"), cab.get("FASE")),
        "oficial": cab.get("FASE") == "O" and cab.get("ORLC") == "LEG",
        "processo": cab.get("PROC"),
        "pleito": cab.get("PLEI"),
        "data_pleito": cab.get("DTPL"),
        "turno": int(cab.get("TURN", 0)),
        "uf": cab.get("UNFE"),
        "municipio_tse": cab.get("MUNI"),
        "zona": int(cab.get("ZONA", 0)),
        "secao": int(cab.get("SECA", 0)),
        "local": cab.get("LOCA"),
        "urna": cab.get("IDUE"),
        "aptos": int(cab.get("APTO", 0)),
        "comparecimento": int(cab.get("COMP", 0)),
        "faltosos": int(cab.get("FALT", 0)),
        "abertura": f'{cab.get("DTAB")} {cab.get("HRAB")}',
        "fechamento": f'{cab.get("DTFC")} {cab.get("HRFC")}',
        "versao_software": cab.get("VERS"),
        "bruto": cab,
    }
    codigos = {c["codigo"] for c in eleicoes}
    cabecalho["abrangencia"] = "municipal" if codigos and codigos <= CARGOS_MUNICIPAIS else "geral"
    # chave única do boletim: evita contar a mesma seção duas vezes
    cabecalho["chave"] = f'{cabecalho["pleito"]}-{cabecalho["turno"]}-{cabecalho["uf"]}-{cabecalho["municipio_tse"]}-{cabecalho["zona"]}-{cabecalho["secao"]}'

    for c in eleicoes:
        _conferir_cargo(c)
    return {"cabecalho": cabecalho, "cargos": eleicoes}


def _conferir_cargo(c: dict) -> None:
    """Confere as somas internas do cargo e registra eventuais divergências."""
    t = c["totais"]
    soma_nominal = sum(c["candidatos"].values())
    avisos = []
    if "NOMI" in t and soma_nominal != t["NOMI"]:
        avisos.append(f"soma nominal {soma_nominal} ≠ NOMI {t['NOMI']}")
    if {"NOMI", "BRAN", "NULO", "TOTC"} <= t.keys():
        if t["NOMI"] + t.get("LEGC", 0) + t["BRAN"] + t["NULO"] != t["TOTC"]:
            avisos.append("NOMI+LEGC+BRAN+NULO ≠ TOTC")
    for num, p in c["partidos"].items():
        nominais = sum(v for k, v in c["candidatos"].items() if str(k).startswith(str(num)))
        if nominais + p["legenda"] != p["total"]:
            avisos.append(f"partido {num}: nominais+legenda ≠ TOTP")
    t["validos"] = t.get("NOMI", 0) + t.get("LEGC", 0)
    c["avisos"] = avisos
