import csv
import io
import json
import tempfile
import zipfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase

from .models import Boletim, Candidato, Dispositivo, LocalVotacao, Municipio

DADOS = Path(__file__).parent / 'dados_teste' / 'bus_reais_1turno_2026.json'


def bus_reais():
    """3 boletins reais (seções 7, 10 e 19 da zona 58/PR, 1º turno 2026)."""
    return list(json.loads(DADOS.read_text(encoding='utf-8')).values())


class ApiBoletinsTest(TestCase):
    def setUp(self):
        self.disp = Dispositivo.objects.create(nome='Equipe Teste')
        self.auth = {'HTTP_AUTHORIZATION': f'Token {self.disp.token}'}

    def enviar(self, qrcodes, **extra):
        return self.client.post('/api/boletins/', json.dumps({'qrcodes': qrcodes, 'lido_em': '2026-10-04T17:30:00-03:00'}),
                                content_type='application/json', **{**self.auth, **extra})

    def test_sem_token_recusa(self):
        r = self.client.post('/api/boletins/', '{}', content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_ping(self):
        self.assertEqual(self.client.get('/api/ping/', **self.auth).json()['dispositivo'], 'Equipe Teste')

    def test_recebe_valida_e_totaliza(self):
        for qrs in bus_reais():
            r = self.enviar(qrs)
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(r.json()['assinatura'], 'valida')
        self.assertEqual(Boletim.objects.count(), 3)
        t = self.client.get('/api/totais/', **self.auth).json()
        self.assertEqual(t['secoes'], 3)
        self.assertEqual(t['comparecimento'], 565)
        pres = next(c for c in t['cargos'] if c['codigo'] == 1)
        self.assertEqual(pres['validos'], 551)
        self.assertEqual(pres['candidatos'][0], {'numero': 22, 'votos': 374, 'percentual': 67.88})
        # filtro por local de votação
        self.assertEqual(self.client.get('/api/totais/?local=1023', **self.auth).json()['secoes'], 3)
        self.assertEqual(self.client.get('/api/totais/?local=9999', **self.auth).json()['secoes'], 0)

    def test_duplicado_nao_soma_duas_vezes(self):
        qrs = bus_reais()[0]
        self.assertEqual(self.enviar(qrs).status_code, 201)
        r = self.enviar(list(reversed(qrs)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['situacao'], 'duplicado')
        self.assertEqual(Boletim.objects.count(), 1)

    def test_certificado_chega_depois(self):
        qrs = bus_reais()[0]
        so_bu = [q for q in qrs if q.startswith('QRBU')]
        self.assertEqual(self.enviar(so_bu).json()['assinatura'], 'sem_certificado')
        r = self.enviar(qrs)
        self.assertEqual(r.json()['situacao'], 'atualizado')
        self.assertEqual(Boletim.objects.get().assinatura, 'valida')

    def test_adulterado_recusado(self):
        qrs = [q.replace('22:129', '22:999') for q in bus_reais()[0]]
        r = self.enviar(qrs)
        self.assertEqual(r.status_code, 422)
        self.assertIn('HASH', r.json()['detail'])
        self.assertEqual(Boletim.objects.count(), 0)

    def test_incompleto_recusado(self):
        r = self.enviar([q for q in bus_reais()[0] if not q.startswith('QRBU:2')])
        self.assertEqual(r.status_code, 422)

    def test_dispositivo_desativado(self):
        self.disp.ativo = False
        self.disp.save()
        self.assertEqual(self.enviar(bus_reais()[0]).status_code, 401)

    def test_importar_arquivo_do_celular(self):
        User.objects.create_superuser('admin', 'a@a.com', 'senha-teste-123')
        self.client.login(username='admin', password='senha-teste-123')
        conteudo = {'formato': 'apura-bu/1', 'reporter': 'Offline',
                    'boletins': [{'chave': 'x', 'qrcodes': q, 'lido_em': None} for q in bus_reais()]}
        arq = SimpleUploadedFile('boletins.json', json.dumps(conteudo).encode(), 'application/json')
        r = self.client.post('/importar/', {'arquivos': [arq]}, follow=True)
        self.assertContains(r, '3 novos')
        self.assertEqual(Boletim.objects.count(), 3)


class ImportacaoResultadoTest(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('equipe', is_staff=True))

    def importar(self, conteudo):
        arquivo = SimpleUploadedFile('boletins.json', json.dumps(conteudo).encode(), 'application/json')
        return self.client.post('/importar/', {'arquivos': [arquivo]}, follow=True)

    def test_arquivo_invalido_nao_anuncia_sucesso(self):
        resposta = self.importar([])
        self.assertContains(resposta, 'Nenhum boletim foi aceito')
        self.assertNotIn(messages.SUCCESS, [m.level for m in resposta.context['messages']])
        self.assertEqual(Boletim.objects.count(), 0)

    def test_lista_malformada_e_recusada(self):
        resposta = self.importar({'formato': 'apura-bu/1', 'boletins': {'chave': 'invalido'}})
        self.assertContains(resposta, 'não é um arquivo exportado pelo app')
        self.assertEqual(Boletim.objects.count(), 0)

    def test_importacao_parcial_preserva_boletins_validos(self):
        resposta = self.importar({'formato': 'apura-bu/1', 'boletins': [
            'item inválido', {'qrcodes': bus_reais()[0]},
        ]})
        self.assertContains(resposta, '1 novos, 0 já existentes, 0 atualizados, 1 recusados')
        self.assertIn(messages.WARNING, [m.level for m in resposta.context['messages']])
        self.assertEqual(Boletim.objects.count(), 1)


class ImportarTseTest(TestCase):
    """Simula os arquivos do TSE (mesmo leiaute: ';' e latin-1)."""

    def zip_csv(self, nome, linhas):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(linhas[0]), delimiter=';', quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(linhas)
        tmp = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
        with zipfile.ZipFile(tmp, 'w') as z:
            z.writestr(nome, buf.getvalue().encode('latin-1'))
        return tmp.name

    def test_importa_candidatos_e_locais(self):
        base = {'NR_TURNO': '1', 'SG_UF': 'BR', 'NM_UE': 'BRASIL', 'DS_SITUACAO_CANDIDATURA': 'APTO', 'NM_PARTIDO': 'Partido'}
        cands = [
            {**base, 'SG_UE': 'BR', 'CD_CARGO': '1', 'NR_CANDIDATO': '22', 'NM_URNA_CANDIDATO': 'CANDIDATO A',
             'SG_PARTIDO': 'PA', 'NR_PARTIDO': '22'},
            {**base, 'SG_UE': 'BR', 'CD_CARGO': '1', 'NR_CANDIDATO': '13', 'NM_URNA_CANDIDATO': 'CANDIDATO B',
             'SG_PARTIDO': 'PB', 'NR_PARTIDO': '13'},
            {**base, 'NR_TURNO': '2', 'SG_UE': 'BR', 'CD_CARGO': '1', 'NR_CANDIDATO': '22',
             'NM_URNA_CANDIDATO': 'CANDIDATO A', 'SG_PARTIDO': 'PA', 'NR_PARTIDO': '22'},
            {**base, 'SG_UF': 'PR', 'SG_UE': 'PR', 'CD_CARGO': '3', 'NR_CANDIDATO': '55',
             'NM_URNA_CANDIDATO': 'GOVERNADOR Ç', 'SG_PARTIDO': 'PC', 'NR_PARTIDO': '55'},
        ]
        loc = {'SG_UF': 'PR', 'CD_MUNICIPIO': '74454', 'NM_MUNICIPIO': 'MUNICÍPIO TESTE', 'NR_ZONA': '58',
               'NR_LOCAL_VOTACAO': '1023', 'NM_LOCAL_VOTACAO': 'ESCOLA ESTADUAL TESTE', 'DS_ENDERECO': 'RUA A',
               'NM_BAIRRO': 'CENTRO', 'NR_LATITUDE': '-23,1', 'NR_LONGITUDE': '-50,3', 'QT_ELEITOR_SECAO': '260',
               'NR_SECAO_PRINCIPAL': '#NULO', 'NR_TURNO': '1'}
        locais = [{**loc, 'NR_SECAO': s} for s in ('7', '10', '19', '22')] + \
                 [{**loc, 'NR_SECAO': '30', 'NR_SECAO_PRINCIPAL': '22'}]  # seção agregada
        # o TSE repete cada seção no 2º turno, às vezes em outro local: não pode somar de novo
        locais += [{**x, 'NR_TURNO': '2'} for x in locais] + \
                  [{**loc, 'NR_TURNO': '2', 'NR_SECAO': '41', 'NR_LOCAL_VOTACAO': '1040'}]
        call_command('importar_tse', ano=2026, arquivo_candidatos=self.zip_csv('consulta_cand_2026_BRASIL.csv', cands),
                     arquivo_locais=self.zip_csv('eleitorado_local_votacao_2026.csv', locais), stdout=io.StringIO())
        self.assertEqual(Candidato.objects.count(), 3)
        self.assertEqual(Candidato.objects.get(ue='BR', numero=22).turno, 2)
        self.assertEqual(Candidato.objects.get(ue='PR').nome_urna, 'GOVERNADOR Ç')
        local = LocalVotacao.objects.get()
        self.assertEqual((local.secoes, local.eleitores, local.latitude), (4, 1300, -23.1))
        self.assertEqual(Municipio.objects.get(codigo_tse='74454').nome, 'MUNICÍPIO TESTE')

        # nomes chegam ao app depois que a eleição existe
        disp = Dispositivo.objects.create(nome='x')
        auth = {'HTTP_AUTHORIZATION': f'Token {disp.token}'}
        self.client.post('/api/boletins/', json.dumps({'qrcodes': bus_reais()[0]}), content_type='application/json', **auth)
        nomes = self.client.get('/api/nomes/', **auth).json()
        self.assertEqual(nomes['BR-1-22'], 'CANDIDATO A')
        self.assertEqual(nomes['PR-3-55'], 'GOVERNADOR Ç')
        self.assertEqual(nomes['L-74454-58-1023'], 'ESCOLA ESTADUAL TESTE')
        self.assertEqual(nomes['LS-74454-58-1023'], 4)
        self.assertEqual(nomes['M-74454'], 'MUNICÍPIO TESTE/PR')


class PainelTest(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser('chefe', 'c@c.com', 'senha-teste-123')
        disp = Dispositivo.objects.create(nome='Equipe Centro')
        for qrs in bus_reais():
            self.client.post('/api/boletins/', json.dumps({'qrcodes': qrs}), content_type='application/json',
                             HTTP_AUTHORIZATION=f'Token {disp.token}')
        LocalVotacao.objects.create(ano=2026, uf='PR', municipio_tse='74454', zona=58, numero='1023',
                                    nome='ESCOLA TESTE', secoes=13)
        Municipio.objects.create(codigo_tse='74454', nome='BANDEIRANTES', uf='PR')
        Candidato.objects.create(ano=2026, ue='BR', cargo=1, numero=22, nome_urna='CANDIDATO A', partido='PA')

    def test_exige_login_da_equipe(self):
        self.assertEqual(self.client.get('/painel/').status_code, 302)
        self.assertEqual(self.client.get('/painel/dados/').status_code, 403)

    def test_dados_do_estado_e_filtro_por_local(self):
        self.client.login(username='chefe', password='senha-teste-123')
        pagina = self.client.get('/painel/')
        self.assertContains(pagina, 'BANDEIRANTES')
        self.assertContains(pagina, 'href="/manual/"')
        d = self.client.get('/painel/dados/').json()
        self.assertEqual((d['progresso']['secoes_apuradas'], d['progresso']['secoes_esperadas']), (3, 13))
        self.assertEqual([c['codigo'] for c in d['cargos'] if c['destaque']], [1, 3, 5])
        self.assertEqual(d['cargos'][0]['candidatos'][0]['nome'], 'CANDIDATO A')
        self.assertIn('2 senadores', next(c for c in d['cargos'] if c['codigo'] == 5)['nota'])
        self.assertEqual(d['abrangencia']['linhas'],
                         [{'codigo': '74454', 'nome': 'BANDEIRANTES', 'apuradas': 3, 'esperadas': 13}])
        self.assertEqual(d['ultimos'][0]['local'], 'ESCOLA TESTE')
        self.assertEqual(d['celulares'][0]['boletins'], 3)

        d = self.client.get('/painel/dados/?municipio=74454&local=58/1023').json()
        self.assertEqual(d['abrangencia']['nivel'], 'locais')
        self.assertEqual(d['progresso']['secoes_apuradas'], 3)
        self.assertEqual(self.client.get('/painel/dados/?local=x').status_code, 400)


class ManualTest(TestCase):
    def test_manual_aberto_sem_login(self):
        r = self.client.get('/manual/')
        self.assertContains(r, 'Guia do Apura BU')
        self.assertContains(r, 'href="/painel/"')
        self.assertEqual(self.client.get('/manual').status_code, 301)  # APPEND_SLASH


class PwaTest(TestCase):
    def test_serve_app_e_bloqueia_fuga_de_pasta(self):
        r = self.client.get('/app/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get('/app/vendor/zxing_reader.wasm')['Content-Type'], 'application/wasm')
        self.assertEqual(self.client.get('/app/../config/settings.py').status_code, 404)
        self.assertEqual(self.client.get('/app/%2e%2e/servidor/db.sqlite3').status_code, 404)
