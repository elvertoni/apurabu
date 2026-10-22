import json
import logging
import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from . import painel
from .models import Boletim, Candidato, Dispositivo, Eleicao, LocalVotacao, Municipio, Partido
from .servicos import BoletimRecusado, registrar_boletim, totalizar

log = logging.getLogger('boletins')

mimetypes.add_type('application/wasm', '.wasm')
mimetypes.add_type('application/manifest+json', '.webmanifest')


# ------------------------------------------------------------------ autenticação dos celulares

class TokenMixin:
    """Exige o cabeçalho 'Authorization: Token <código>' de um celular autorizado."""

    def dispatch(self, request, *args, **kwargs):
        cab = request.headers.get('Authorization', '')
        token = cab[6:].strip() if cab.startswith('Token ') else ''
        self.dispositivo = Dispositivo.objects.filter(token=token, ativo=True).first() if token else None
        if not self.dispositivo and not request.user.is_staff:
            if token:  # nunca registra o código, só de onde veio a tentativa
                log.warning('Código de acesso recusado em %s (IP %s)', request.path,
                            request.headers.get('CF-Connecting-IP') or request.META.get('REMOTE_ADDR'))
            return JsonResponse({'detail': 'Código de acesso inválido ou desativado'}, status=401)
        return super().dispatch(request, *args, **kwargs)


@method_decorator(csrf_exempt, name='dispatch')
class PingView(TokenMixin, View):
    def get(self, request):
        nome = self.dispositivo.nome if self.dispositivo else request.user.get_username()
        return JsonResponse({'ok': True, 'dispositivo': nome})


@method_decorator(csrf_exempt, name='dispatch')
class BoletimView(TokenMixin, View):
    """Recebe um boletim do celular: {chave, qrcodes[], lido_em, reporter}."""

    def post(self, request):
        try:
            corpo = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'detail': 'JSON inválido'}, status=400)
        try:
            b, situacao = registrar_boletim(
                corpo.get('qrcodes'), dispositivo=self.dispositivo,
                reporter=corpo.get('reporter') or '', lido_em=corpo.get('lido_em'),
            )
        except BoletimRecusado as e:
            return JsonResponse({'detail': str(e)}, status=422)
        return JsonResponse(
            {'chave': b.chave, 'situacao': situacao, 'assinatura': b.assinatura},
            status=201 if situacao == 'criado' else 200,
        )


class NomesView(TokenMixin, View):
    """Mapa para o app: {'BR-1-13': 'Fulano', 'P-13': 'PT', 'M-74454': 'Município/PR', 'L-74454-58-1023': 'Escola'}.

    Candidatos: '<UE>-<cargo>-<número>', onde UE é BR (presidente), a UF ou o código TSE do município.
    """

    def get(self, request):
        anos = set(Eleicao.objects.filter(ativa=True).values_list('ano', flat=True)) - {None}
        ues = set(Boletim.objects.filter(eleicao__ativa=True).values_list('uf', flat=True)) | \
            set(Boletim.objects.filter(eleicao__ativa=True).values_list('municipio_tse', flat=True)) | {'BR'}
        nomes = {}
        for ue, cargo, num, nome in Candidato.objects.filter(ano__in=anos, ue__in=ues) \
                .values_list('ue', 'cargo', 'numero', 'nome_urna'):
            nomes[f'{ue}-{cargo}-{num}'] = nome
        for num, sigla in Partido.objects.filter(ano__in=anos).values_list('numero', 'sigla'):
            nomes[f'P-{num}'] = sigla
        for cod, nome, uf in Municipio.objects.filter(codigo_tse__in=ues).values_list('codigo_tse', 'nome', 'uf'):
            nomes[f'M-{cod}'] = f'{nome}/{uf}'
        # escolas dos municípios que já enviaram boletins: nome e quantas urnas esperar
        for muni, zona, numero, nome, secoes in LocalVotacao.objects.filter(ano__in=anos, municipio_tse__in=ues) \
                .values_list('municipio_tse', 'zona', 'numero', 'nome', 'secoes'):
            nomes[f'L-{muni}-{zona}-{numero}'] = nome
            nomes[f'LS-{muni}-{zona}-{numero}'] = secoes
        return JsonResponse(nomes)


class TotaisView(TokenMixin, View):
    """Totais por cargo. Filtros: ?eleicao=<id>&uf=PR&municipio=74454&zona=58&local=1023"""

    def get(self, request):
        p = request.GET
        eleicao = Eleicao.objects.filter(pk=p['eleicao']).first() if p.get('eleicao') \
            else Eleicao.objects.filter(ativa=True).first()
        if not eleicao:
            return JsonResponse({'detail': 'Nenhuma eleição recebida ainda'}, status=404)
        qs = Boletim.objects.filter(eleicao=eleicao, oficial=True)
        for campo, chave in (('uf', 'uf'), ('municipio_tse', 'municipio'), ('zona', 'zona'), ('local', 'local')):
            if p.get(chave):
                qs = qs.filter(**{campo: p[chave]})
        dados = totalizar(qs)
        dados['eleicao'] = {'id': eleicao.pk, 'descricao': str(eleicao), 'turno': eleicao.turno}
        dados['aviso'] = 'Resultado parcial e extraoficial, a partir dos boletins de urna recebidos. ' \
                         'O resultado oficial é divulgado pelo TSE.'
        return JsonResponse(dados)


# ------------------------------------------------------------------ importar arquivo trazido do celular

@method_decorator(staff_member_required, name='dispatch')
class ImportarView(View):
    template_name = 'boletins/importar.html'

    def get(self, request):
        return render(request, self.template_name, admin.site.each_context(request))

    def post(self, request):
        arquivos = request.FILES.getlist('arquivos')
        resumo = {'criado': 0, 'duplicado': 0, 'atualizado': 0, 'recusado': 0}
        erros = []
        for arq in arquivos:
            try:
                conteudo = json.load(arq)
                if not isinstance(conteudo, dict) or conteudo.get('formato') != 'apura-bu/1':
                    raise ValueError
                lista = conteudo['boletins']
                if not isinstance(lista, list) or not isinstance(conteudo.get('reporter', ''), str):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                erros.append(f'{arq.name}: não é um arquivo exportado pelo app')
                continue
            for item in lista:
                if not isinstance(item, dict):
                    resumo['recusado'] += 1
                    erros.append(f'{arq.name}: boletim em formato inválido; exporte novamente pelo app')
                    continue
                try:
                    _, s = registrar_boletim(item.get('qrcodes'), reporter=conteudo.get('reporter') or '',
                                             lido_em=item.get('lido_em'))
                    resumo[s] += 1
                except BoletimRecusado as e:
                    resumo['recusado'] += 1
                    erros.append(f'{item.get("chave", "?")}: {e}')
        aceitos = resumo['criado'] + resumo['duplicado'] + resumo['atualizado']
        resultado = (f'{resumo["criado"]} novos, {resumo["duplicado"]} já existentes, '
                     f'{resumo["atualizado"]} atualizados, {resumo["recusado"]} recusados.')
        if aceitos:
            nivel = messages.WARNING if erros else messages.SUCCESS
            messages.add_message(request, nivel, resultado)
        elif erros:
            messages.error(request, 'Nenhum boletim foi aceito. Confira os erros abaixo e exporte novamente pelo app.')
        else:
            messages.warning(request, 'Nenhum boletim encontrado. Selecione um arquivo exportado pelo app com boletins lidos.')
        for e in erros[:30]:
            messages.error(request, e)
        return HttpResponseRedirect(reverse('importar'))


# ------------------------------------------------------------------ painel de acompanhamento

@method_decorator(staff_member_required, name='dispatch')
class PainelView(View):
    def get(self, request):
        return render(request, 'boletins/painel.html', {
            'eleicoes': Eleicao.objects.all(),
            'municipios': Municipio.objects.filter(uf=painel.UF).order_by('nome'),
            'uf': painel.UF,
        })


class PainelDadosView(View):
    """JSON do painel. Filtros: ?eleicao=<id>&municipio=74454&local=58/1023"""

    def get(self, request):
        if not (request.user.is_active and request.user.is_staff):
            return JsonResponse({'detail': 'Entre no admin para ver o painel'}, status=403)
        p = request.GET
        municipio, local = p.get('municipio', ''), p.get('local', '')
        if (municipio and not re.fullmatch(r'\d{1,6}', municipio)) or \
                (local and not re.fullmatch(r'\d{1,4}/\d{1,8}', local)) or \
                (p.get('eleicao') and not p['eleicao'].isdigit()):
            return JsonResponse({'detail': 'Filtro inválido'}, status=400)
        eleicao = Eleicao.objects.filter(pk=p['eleicao']).first() if p.get('eleicao') \
            else Eleicao.objects.filter(ativa=True).first()
        if not eleicao:
            return JsonResponse({'eleicao': None, 'aviso': 'Nenhum boletim recebido ainda.'})
        zona, numero = local.split('/') if local and municipio else (None, None)
        return JsonResponse(painel.dados_painel(eleicao, municipio=municipio or None,
                                                zona=int(zona) if zona else None, local=numero))


# ------------------------------------------------------------------ app do celular (PWA)

class PwaView(View):
    """Serve a pasta do app em /app/. O service worker precisa estar no mesmo caminho."""

    def get(self, request, caminho=''):
        base = Path(settings.PWA_DIR).resolve()
        alvo = (base / (caminho or 'index.html')).resolve()
        if not alvo.is_relative_to(base) or not alvo.is_file():
            raise Http404
        resp = FileResponse(open(alvo, 'rb'), content_type=mimetypes.guess_type(alvo.name)[0])
        if alvo.name in ('sw.js', 'index.html'):
            resp['Cache-Control'] = 'no-cache'
        return resp


def raiz(request):
    return HttpResponseRedirect('/app/')
