"""Dados do painel de acompanhamento da rádio (/painel/)."""
from collections import Counter

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import Boletim, Candidato, Dispositivo, LocalVotacao, Municipio, Partido
from .servicos import totalizar

UF = getattr(settings, 'APURA_UF', 'PR')
CACHE_SEGUNDOS = getattr(settings, 'APURA_PAINEL_CACHE', 10)
DESTAQUE = {1, 3, 5, 11}            # presidente, governador, senador (prefeito nas municipais)
MAIORIA = {1, 3, 11}                # um voto por eleitor: a barra vai de 0 a 100% e marca os 50%
LIMITE_CANDIDATOS = 50


def _ue(cargo, municipio):
    """Unidade eleitoral do cargo na base de candidatos do TSE."""
    if cargo in (1, 2):
        return 'BR'
    if cargo >= 11:
        return municipio  # sem município filtrado, prefeitos de cidades diferentes não se somam
    return UF


def dados_painel(eleicao, municipio=None, zona=None, local=None):
    chave = f'painel:{eleicao.pk}:{municipio}:{zona}:{local}'
    dados = cache.get(chave)
    if dados is None:
        dados = _montar(eleicao, municipio, zona, local)
        cache.set(chave, dados, CACHE_SEGUNDOS)
    return dados


def _montar(eleicao, municipio, zona, local):
    base = Boletim.objects.filter(eleicao=eleicao, uf=UF)
    locais = LocalVotacao.objects.filter(ano=eleicao.ano, uf=UF)
    if municipio:
        base, locais = base.filter(municipio_tse=municipio), locais.filter(municipio_tse=municipio)
    # a tabela de abrangência mostra o município inteiro, mesmo com um local escolhido
    oficiais_mun, locais_mun = base.filter(oficial=True), locais
    if zona:
        base, locais = base.filter(zona=zona), locais.filter(zona=zona)
    if local:
        base, locais = base.filter(local=local), locais.filter(numero=local)
    oficiais = base.filter(oficial=True)

    tot = totalizar(oficiais)
    esperado = locais.aggregate(secoes=Sum('secoes'), eleitores=Sum('eleitores'))
    nomes_mun = dict(Municipio.objects.filter(uf=UF).values_list('codigo_tse', 'nome'))
    ultimos = list(base.select_related('dispositivo').order_by('-recebido_em')[:12])
    nomes_loc = {(m, z, n): nome for m, z, n, nome in LocalVotacao.objects.filter(
        ano=eleicao.ano, uf=UF, municipio_tse__in={b.municipio_tse for b in ultimos},
        numero__in={b.local for b in ultimos}).values_list('municipio_tse', 'zona', 'numero', 'nome')}

    return {
        'atualizado_em': timezone.now().isoformat(),
        'uf': UF,
        'eleicao': {'id': eleicao.pk, 'descricao': str(eleicao), 'turno': eleicao.turno, 'ano': eleicao.ano},
        'progresso': {
            'secoes_apuradas': tot['secoes'],
            'secoes_esperadas': esperado['secoes'] or 0,
            'eleitores_esperados': esperado['eleitores'] or 0,
            'aptos': tot['aptos'],
            'comparecimento': tot['comparecimento'],
            'percentual_comparecimento': tot['percentual_comparecimento'],
            'municipios_com_boletim': tot['municipios'],
            'municipios_total': locais.values('municipio_tse').distinct().count(),
        },
        'cargos': _cargos(eleicao, tot, municipio),
        'abrangencia': _abrangencia(oficiais_mun, locais_mun, municipio, nomes_mun),
        'ultimos': [
            {'secao': b.secao, 'zona': b.zona, 'municipio': nomes_mun.get(b.municipio_tse, b.municipio_tse),
             'local': nomes_loc.get((b.municipio_tse, b.zona, b.local), f'local {b.local}'),
             'reporter': b.reporter or (b.dispositivo.nome if b.dispositivo else ''),
             'recebido_em': b.recebido_em.isoformat(), 'assinatura': b.assinatura,
             'avisos': b.tem_avisos, 'oficial': b.oficial}
            for b in ultimos
        ],
        'celulares': [
            {'nome': d.nome, 'ativo': d.ativo, 'boletins': d.n,
             'ultimo_envio': d.ultimo_envio.isoformat() if d.ultimo_envio else None}
            for d in Dispositivo.objects.annotate(n=Count('boletim', filter=Q(boletim__eleicao=eleicao)))
            .order_by('-ativo', '-ultimo_envio', 'nome')
        ],
        'alertas': {
            'somas_divergentes': base.filter(tem_avisos=True).count(),
            'sem_certificado': base.filter(assinatura='sem_certificado').count(),
            'nao_oficiais': base.filter(oficial=False).count(),
            'outra_uf': Boletim.objects.filter(eleicao=eleicao).exclude(uf=UF).count(),
        },
        'aviso': 'Resultado parcial e extraoficial, a partir dos boletins de urna recebidos. '
                 'O resultado oficial é divulgado pelo TSE.',
    }


def _cargos(eleicao, tot, municipio):
    ues = {u for u in ('BR', UF, municipio) if u}
    nomes = {(ue, cargo, num): (nome, partido) for ue, cargo, num, nome, partido in
             Candidato.objects.filter(ano=eleicao.ano, ue__in=ues)
             .values_list('ue', 'cargo', 'numero', 'nome_urna', 'partido')}
    siglas = dict(Partido.objects.filter(ano=eleicao.ano).values_list('numero', 'sigla'))

    cargos = []
    for cg in tot['cargos']:
        cod, validos = cg['codigo'], cg['validos']
        ue = _ue(cod, municipio)
        candidatos = []
        for c in cg['candidatos'][:LIMITE_CANDIDATOS]:
            nome, partido = nomes.get((ue, cod, c['numero']), ('', ''))
            candidatos.append({**c, 'nome': nome, 'partido': partido or siglas.get(int(str(c['numero'])[:2]), '')})
        nota = ''
        if cod == 5 and cg['total'] > 1.5 * tot['comparecimento']:
            nota = 'Cada eleitor votou em 2 senadores: os percentuais somam 200%.'
        elif cg['tipo'] == 'proporcional':
            nota = 'Válidos incluem os votos de legenda.'
        cargos.append({
            'codigo': cod, 'cargo': cg['cargo'], 'tipo': cg['tipo'],
            'destaque': cod in DESTAQUE, 'escala': 'maioria' if cod in MAIORIA else 'lider',
            'validos': validos, 'brancos': cg['brancos'], 'nulos': cg['nulos'], 'legenda': cg['legenda'],
            'total': cg['total'], 'nota': nota,
            'qtd_candidatos': len(cg['candidatos']), 'candidatos': candidatos,
            'partidos': [{**p, 'sigla': siglas.get(p['numero'], str(p['numero'])),
                          'percentual': round(100 * p['votos'] / validos, 2) if validos else 0}
                         for p in cg['partidos'][:20]] if cg['tipo'] == 'proporcional' else [],
        })
    return cargos


def _abrangencia(oficiais, locais, municipio, nomes_mun):
    """Sem filtro: urnas por município. Com município: urnas por local de votação."""
    if not municipio:
        apuradas = dict(oficiais.values_list('municipio_tse').annotate(n=Count('id')))
        esperadas = dict(locais.filter(municipio_tse__in=apuradas).values_list('municipio_tse')
                         .annotate(s=Sum('secoes')))
        linhas = [{'codigo': m, 'nome': nomes_mun.get(m, f'município {m}'), 'apuradas': n,
                   'esperadas': esperadas.get(m, 0)} for m, n in apuradas.items()]
        linhas.sort(key=lambda x: (-x['apuradas'], x['nome']))
        return {'nivel': 'municipios', 'linhas': linhas}

    apuradas = Counter(oficiais.values_list('zona', 'local'))
    linhas = []
    for z, n, nome, secoes in locais.order_by('nome').values_list('zona', 'numero', 'nome', 'secoes'):
        linhas.append({'codigo': f'{z}/{n}', 'nome': nome, 'zona': z,
                       'apuradas': apuradas.pop((z, n), 0), 'esperadas': secoes})
    for (z, n), qtd in apuradas.items():  # local que não está na base do TSE importada
        linhas.append({'codigo': f'{z}/{n}', 'nome': f'local {n}', 'zona': z, 'apuradas': qtd, 'esperadas': 0})
    linhas.sort(key=lambda x: (-x['apuradas'], x['nome']))
    return {'nivel': 'locais', 'linhas': linhas}
