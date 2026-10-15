"""Regras de negócio: registrar boletins e totalizar."""
import logging
from collections import Counter, defaultdict

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .bu_qrcode import ErroBU, LeitorBU
from .models import Boletim, Eleicao

log = logging.getLogger('boletins')

ORDEM_CARGOS = [1, 3, 5, 6, 7, 8, 11, 13, 9]


class BoletimRecusado(Exception):
    pass


def registrar_boletim(qrcodes, dispositivo=None, reporter='', lido_em=None):
    """Valida os QR Codes e grava o boletim. Retorna (boletim, situacao).

    situacao: 'criado' | 'duplicado' | 'atualizado' (chegou o certificado depois).
    O servidor nunca confia no que o celular calculou: refaz tudo a partir do texto bruto.
    """
    if not isinstance(qrcodes, list) or not qrcodes or not all(isinstance(q, str) for q in qrcodes):
        raise BoletimRecusado('Envie a lista de textos dos QR Codes')

    leitor = LeitorBU()
    try:
        for q in qrcodes:
            leitor.adicionar(q)
        bu = leitor.montar()
    except ErroBU as e:
        raise BoletimRecusado(str(e))
    except Exception as e:  # certificado corrompido, hexadecimal inválido etc.
        raise BoletimRecusado(f'Boletim ilegível: {e}')

    c = bu['cabecalho']
    textos = [leitor.partes_bu[i] for i in sorted(leitor.partes_bu)] + \
             [leitor.partes_ce[i] for i in sorted(leitor.partes_ce)]

    existente = Boletim.objects.filter(chave=c['chave']).first()
    if existente:
        if existente.qrcodes[: len(leitor.partes_bu)] != textos[: len(leitor.partes_bu)]:
            log.warning('Seção %s recebida com conteúdo DIFERENTE do já gravado', c['chave'])
            raise BoletimRecusado('Esta seção já foi registrada com outro conteúdo; confira o papel')
        # mesmo boletim: aproveita se agora veio com o certificado
        if existente.assinatura != 'valida' and bu['integridade']['assinatura'] == 'valida':
            existente.assinatura = 'valida'
            existente.qrcodes = textos
            existente.save(update_fields=['assinatura', 'qrcodes'])
            return existente, 'atualizado'
        return existente, 'duplicado'

    ano = int(c['data_pleito'][:4]) if c.get('data_pleito') else None
    eleicao, _ = Eleicao.objects.get_or_create(
        pleito=c['pleito'], turno=c['turno'],
        defaults={'data': c['data_pleito'] or '', 'abrangencia': c['abrangencia'], 'ano': ano},
    )
    cargos = bu['cargos']
    try:
        with transaction.atomic():
            b = Boletim.objects.create(
                eleicao=eleicao, chave=c['chave'], uf=c['uf'], municipio_tse=c['municipio_tse'],
                zona=c['zona'], secao=c['secao'], local=c['local'] or '', urna=c['urna'] or '',
                aptos=c['aptos'], comparecimento=c['comparecimento'], oficial=c['oficial'],
                assinatura=bu['integridade']['assinatura'], tem_avisos=any(cg['avisos'] for cg in cargos),
                dados={'cabecalho': {k: v for k, v in c.items() if k != 'bruto'},
                       'cargos': [_cargo_json(cg) for cg in cargos]},
                qrcodes=textos, dispositivo=dispositivo, reporter=reporter[:100],
                lido_em=parse_datetime(lido_em) if isinstance(lido_em, str) else None,
            )
    except IntegrityError:  # dois celulares enviaram a mesma seção no mesmo instante
        return Boletim.objects.get(chave=c['chave']), 'duplicado'

    if dispositivo:
        dispositivo.ultimo_envio = timezone.now()
        dispositivo.save(update_fields=['ultimo_envio'])
    log.info('Boletim %s registrado (%s)', b, b.assinatura)
    return b, 'criado'


def _cargo_json(cg):
    # chaves de dicionário em JSON precisam ser texto
    return {**cg, 'candidatos': {str(k): v for k, v in cg['candidatos'].items()},
            'partidos': {str(k): v for k, v in cg['partidos'].items()}}


def totalizar(boletins):
    """Soma uma coleção de boletins por cargo. Seções já são únicas no banco."""
    soma = defaultdict(lambda: {'candidatos': Counter(), 'partidos': Counter(), 'BRAN': 0, 'NULO': 0,
                                'LEGC': 0, 'validos': 0, 'TOTC': 0, 'APTA': 0})
    info = {}
    secoes = aptos = comparecimento = 0
    municipios = set()
    for dados, apt, comp, muni in boletins.values_list('dados', 'aptos', 'comparecimento', 'municipio_tse'):
        secoes += 1
        aptos += apt
        comparecimento += comp
        municipios.add(muni)
        for cg in dados['cargos']:
            s = soma[cg['codigo']]
            info[cg['codigo']] = (cg['cargo'], cg.get('tipo'))
            s['candidatos'].update(cg['candidatos'])
            s['partidos'].update({k: p['total'] for k, p in cg['partidos'].items()})
            for k in ('BRAN', 'NULO', 'LEGC', 'validos', 'TOTC', 'APTA'):
                s[k] += cg['totais'].get(k, 0)

    cargos = []
    for cod in sorted(soma, key=lambda x: ORDEM_CARGOS.index(x) if x in ORDEM_CARGOS else 99):
        s = soma[cod]
        validos = s['validos']
        cargos.append({
            'codigo': cod, 'cargo': info[cod][0], 'tipo': info[cod][1],
            'validos': validos, 'brancos': s['BRAN'], 'nulos': s['NULO'], 'legenda': s['LEGC'],
            'total': s['TOTC'],
            'candidatos': [
                {'numero': int(n), 'votos': v, 'percentual': round(100 * v / validos, 2) if validos else 0}
                for n, v in s['candidatos'].most_common()
            ],
            'partidos': [{'numero': int(n), 'votos': v} for n, v in s['partidos'].most_common()],
        })
    return {
        'secoes': secoes, 'aptos': aptos, 'comparecimento': comparecimento,
        'percentual_comparecimento': round(100 * comparecimento / aptos, 2) if aptos else 0,
        'municipios': len(municipios), 'cargos': cargos,
    }
