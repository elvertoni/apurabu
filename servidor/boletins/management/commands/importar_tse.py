"""Baixa e importa a base do TSE (dados abertos) para a eleição do ano.

    python manage.py importar_tse --ano 2026                # candidatos + locais (Brasil todo)
    python manage.py importar_tse --ano 2026 --uf PR        # locais só do PR (mais rápido)
    python manage.py importar_tse --ano 2026 --so candidatos
    python manage.py importar_tse --ano 2026 --so locais --uf PR --turno 2   # antes do 2º turno
    python manage.py importar_tse --ano 2026 --arquivo-candidatos consulta_cand_2026.zip

Arquivos do TSE: CSV com separador ';', codificação latin-1, dentro de um .zip.
O leiaute é lido pelo cabeçalho, então mudanças de ordem das colunas não quebram a importação.
O arquivo de locais traz uma linha por seção e por turno, e algumas seções mudam de local
entre os turnos: por isso os locais são importados de um turno de cada vez (--turno).
"""
import csv
import io
import tempfile
import urllib.request
import zipfile
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boletins.models import Candidato, LocalVotacao, Municipio, Partido

URL_CAND = 'https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ano}.zip'
URL_LOCAIS = 'https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_{ano}.zip'
NULOS = {'', '#NULO', '#NULO#', '#NE', '#NE#', '-1', '-3'}


def baixar(url, saida):
    saida.write(f'Baixando {url} …')
    tmp = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
    req = urllib.request.Request(url, headers={'User-Agent': 'ApuraBU/1.0'})
    with urllib.request.urlopen(req, timeout=120) as r:
        while bloco := r.read(1 << 20):
            tmp.write(bloco)
    tmp.close()
    return tmp.name


def linhas_csv(caminho_zip, preferir=None):
    """Lê os CSV do zip. Se existir um arquivo '_BRASIL', usa só ele (evita duplicar)."""
    with zipfile.ZipFile(caminho_zip) as z:
        nomes = [n for n in z.namelist() if n.lower().endswith('.csv')]
        brasil = [n for n in nomes if 'BRASIL' in n.upper()]
        if preferir:
            nomes = [n for n in nomes if preferir(n)] or nomes
        for nome in (brasil or nomes):
            with z.open(nome) as f:
                yield from csv.DictReader(io.TextIOWrapper(f, encoding='latin-1', newline=''), delimiter=';')


def v(linha, *colunas):
    for c in colunas:
        x = (linha.get(c) or '').strip()
        if x not in NULOS:
            return x
    return ''


def num(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def flt(x):
    try:
        return float(x.replace(',', '.'))
    except (AttributeError, ValueError):
        return None


class Command(BaseCommand):
    help = 'Importa candidatos, partidos, municípios e locais de votação do TSE'

    def add_arguments(self, p):
        p.add_argument('--ano', type=int, required=True)
        p.add_argument('--uf', help='Limita os locais de votação a uma UF (ex.: PR)')
        p.add_argument('--so', choices=['candidatos', 'locais'])
        p.add_argument('--turno', type=int, default=1, help='Turno dos locais de votação (padrão: 1)')
        p.add_argument('--arquivo-candidatos', help='Zip já baixado (consulta_cand_ANO.zip)')
        p.add_argument('--arquivo-locais', help='Zip já baixado (eleitorado_local_votacao_ANO.zip)')

    def handle(self, *args, ano, uf=None, so=None, turno=1, arquivo_candidatos=None, arquivo_locais=None, **kw):
        try:
            if so in (None, 'candidatos'):
                self.candidatos(ano, arquivo_candidatos or baixar(URL_CAND.format(ano=ano), self.stdout))
            if so in (None, 'locais'):
                self.locais(ano, uf, turno, arquivo_locais or baixar(URL_LOCAIS.format(ano=ano), self.stdout))
        except OSError as e:
            raise CommandError(f'Falha ao baixar/ler arquivo do TSE: {e}')

    @transaction.atomic
    def candidatos(self, ano, caminho):
        cands, partidos, municipios = {}, {}, {}
        for l in linhas_csv(caminho):
            ue, cargo, numero = v(l, 'SG_UE'), num(v(l, 'CD_CARGO')), num(v(l, 'NR_CANDIDATO'))
            if not (ue and cargo and numero):
                continue
            chave = (ue, cargo, numero)
            turno = num(v(l, 'NR_TURNO')) or 1
            # mantém a linha do maior turno (o 2º turno repete os candidatos que disputam)
            if chave not in cands or turno > cands[chave].turno:
                cands[chave] = Candidato(
                    ano=ano, ue=ue, cargo=cargo, numero=numero,
                    nome_urna=v(l, 'NM_URNA_CANDIDATO', 'NM_CANDIDATO')[:120],
                    partido=v(l, 'SG_PARTIDO')[:20],
                    situacao=v(l, 'DS_SITUACAO_CANDIDATURA', 'DS_DETALHE_SITUACAO_CAND')[:60], turno=turno,
                )
            np_ = num(v(l, 'NR_PARTIDO'))
            if np_:
                partidos[np_] = (v(l, 'SG_PARTIDO'), v(l, 'NM_PARTIDO'))
            if ue.isdigit():  # eleição municipal: SG_UE é o código TSE do município
                municipios[ue] = (v(l, 'NM_UE'), v(l, 'SG_UF'))
        if not cands:
            raise CommandError('Nenhum candidato encontrado: o leiaute do arquivo mudou?')
        Candidato.objects.filter(ano=ano).delete()
        Candidato.objects.bulk_create(cands.values(), batch_size=2000)
        for n, (sigla, nome) in partidos.items():
            Partido.objects.update_or_create(ano=ano, numero=n, defaults={'sigla': sigla[:20], 'nome': nome[:120]})
        for cod, (nome, uf) in municipios.items():
            Municipio.objects.update_or_create(codigo_tse=cod, defaults={'nome': nome[:80], 'uf': uf})
        self.stdout.write(self.style.SUCCESS(
            f'{len(cands)} candidatos, {len(partidos)} partidos e {len(municipios)} municípios importados ({ano}).'))

    @transaction.atomic
    def locais(self, ano, uf, turno, caminho):
        locais = {}
        secoes = defaultdict(set)
        municipios = {}
        for l in linhas_csv(caminho):
            sg = v(l, 'SG_UF')
            if uf and sg != uf.upper():
                continue
            if num(v(l, 'NR_TURNO')) not in (None, turno):  # cada seção aparece uma vez por turno
                continue
            muni, zona, numero = v(l, 'CD_MUNICIPIO'), num(v(l, 'NR_ZONA')), v(l, 'NR_LOCAL_VOTACAO')
            if not (muni and zona and numero):
                continue
            municipios[muni] = (v(l, 'NM_MUNICIPIO'), sg)
            chave = (muni, zona, numero)
            if chave not in locais:
                locais[chave] = LocalVotacao(
                    ano=ano, uf=sg, municipio_tse=muni, zona=zona, numero=numero,
                    nome=v(l, 'NM_LOCAL_VOTACAO')[:150], endereco=v(l, 'DS_ENDERECO')[:200],
                    bairro=v(l, 'NM_BAIRRO')[:100],
                    latitude=flt(v(l, 'NR_LATITUDE')), longitude=flt(v(l, 'NR_LONGITUDE')),
                )
            loc = locais[chave]
            loc.eleitores += num(v(l, 'QT_ELEITOR_SECAO', 'QT_ELEITOR')) or 0
            # seção agregada vota na urna da seção principal: conta só urnas de verdade
            secao, principal = v(l, 'NR_SECAO'), v(l, 'NR_SECAO_PRINCIPAL')
            if secao and (not principal or principal == secao):
                secoes[chave].add(secao)
        if not locais:
            raise CommandError('Nenhum local de votação encontrado (UF correta? leiaute mudou?)')
        for chave, loc in locais.items():
            loc.secoes = len(secoes[chave])
        filtro = {'ano': ano, **({'uf': uf.upper()} if uf else {})}
        LocalVotacao.objects.filter(**filtro).delete()
        LocalVotacao.objects.bulk_create(locais.values(), batch_size=2000)
        for cod, (nome, sg) in municipios.items():
            Municipio.objects.update_or_create(codigo_tse=cod, defaults={'nome': nome[:80], 'uf': sg})
        self.stdout.write(self.style.SUCCESS(
            f'{len(locais)} locais de votação em {len(municipios)} municípios importados ({ano}, {turno}º turno).'))
