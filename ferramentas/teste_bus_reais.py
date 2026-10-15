"""Testa o decodificador com os 3 BUs reais (1º turno 2026) e soma o subtotal do local."""
import json
import sys
from collections import Counter, defaultdict

from bu_qrcode import ErroBU, LeitorBU

arquivo = sys.argv[1] if len(sys.argv) > 1 else "qr_raw.json"
fotos = json.load(open(arquivo, encoding="utf-8"))

subtotal = defaultdict(Counter)   # cargo -> votos por número
extras = defaultdict(Counter)     # cargo -> brancos/nulos/legenda/total
vistos = set()

for foto, textos in fotos.items():
    leitor = LeitorBU()
    for t in textos:
        leitor.adicionar(t)
    try:
        bu = leitor.montar()
    except ErroBU as e:
        print(f"[ERRO] {foto}: {e}")
        continue
    c = bu["cabecalho"]
    if c["chave"] in vistos:
        print(f"[DUPLICADO] seção {c['secao']} ignorada")
        continue
    vistos.add(c["chave"])
    print(f"\nZona {c['zona']} Seção {c['secao']} | local {c['local']} | urna {c['urna']} | "
          f"{c['turno']}º turno {c['data_pleito']} | {c['abrangencia']} | fase {c['fase']}")
    print(f"  aptos {c['aptos']}  compareceram {c['comparecimento']}  faltaram {c['faltosos']}  "
          f"fechamento {c['fechamento']}")
    print(f"  integridade: {bu['integridade']}")
    for cg in bu["cargos"]:
        t = cg["totais"]
        aviso = f"  ⚠ {cg['avisos']}" if cg["avisos"] else ""
        print(f"   - {cg['cargo']:<18} ({cg['tipo']}) nominais {t.get('NOMI')} legenda {t.get('LEGC', 0)} "
              f"brancos {t.get('BRAN')} nulos {t.get('NULO')} total {t.get('TOTC')}{aviso}")
        subtotal[cg["cargo"]].update(cg["candidatos"])
        extras[cg["cargo"]].update({k: v for k, v in t.items() if k in ("BRAN", "NULO", "LEGC", "TOTC", "validos")})

print("\n================ SUBTOTAL DO LOCAL ================")
for cargo in ("Presidente", "Governador", "Senador"):
    if cargo not in subtotal:
        continue
    validos = extras[cargo]["validos"]
    print(f"\n{cargo}  (válidos {validos}, brancos {extras[cargo]['BRAN']}, nulos {extras[cargo]['NULO']})")
    for num, v in subtotal[cargo].most_common():
        print(f"   nº {num:<5} {v:>4} votos  {100 * v / validos:5.1f}% dos válidos")
