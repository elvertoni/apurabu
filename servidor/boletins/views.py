import io
import json
import logging
import mimetypes
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import segno

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from . import painel
from .admin import link_configuracao
from .models import Boletim, Candidato, Dispositivo, Eleicao, LocalVotacao, Municipio, Partido, gerar_token
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
        d = self.dispositivo
        if d and (not d.ultimo_contato or timezone.now() - d.ultimo_contato > timedelta(minutes=1)):
            d.ultimo_contato = timezone.now()
            d.save(update_fields=['ultimo_contato'])
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


# ------------------------------------------------------------------ equipe de repórteres

def normalizar_telefone(texto):
    """'(43) 99999-1234' -> '5543999991234'. Vazio continua vazio; número fora do padrão levanta ValueError."""
    d = re.sub(r'\D', '', texto or '')
    if not d:
        return ''
    if len(d) in (10, 11):
        d = '55' + d
    if len(d) not in (12, 13) or not d.startswith('55'):
        raise ValueError
    return d


def telefone_legivel(d):
    return f'({d[2:4]}) {d[4:-4]}-{d[-4:]}' if len(d) in (12, 13) else d


def link_whatsapp(d, link):
    texto = (f'Olá, {d.nome}! Este é o seu acesso ao app de apuração da rádio.\n\n'
             f'1. Toque no link para configurar o celular:\n{link}\n\n'
             '2. No app, abra Ajustes e toque em Testar conexão.\n\n'
             'O link é pessoal: não repasse para ninguém.')
    return f'https://wa.me/{d.telefone}?text={quote(texto)}'


def situacao_reporter(d, agora):
    """(classe, texto) do que o repórter já fez: abriu o link, enviou boletins..."""
    if not d.ativo:
        return 'desativado', 'Acesso desativado'
    if d.ultimo_envio:
        hora = timezone.localtime(d.ultimo_envio)
        quando = f'às {hora:%H:%M}' if hora.date() == timezone.localtime(agora).date() else f'em {hora:%d/%m} às {hora:%H:%M}'
        return 'enviando', f'{d.qtd} boletim enviado, último {quando}' if d.qtd == 1 else \
            f'{d.qtd} boletins enviados, último {quando}'
    if d.ultimo_contato:
        return 'pronto', 'Abriu o app, sem boletins ainda'
    return 'aguardando', 'Ainda não abriu o link'


# "Maria Souza, (43) 99999-1234" | "Maria Souza; 43999991234" | "Maria Souza 43 99999 1234" | "Maria Souza"
RE_TELEFONE_NO_FIM = re.compile(r'^(?P<nome>.+?)\s+(?P<tel>\+?[\d\s().-]{10,})$')


def ler_linha_lote(linha):
    """(nome, telefone em texto). Depois de vírgula, ponto e vírgula ou tab, o resto é o telefone."""
    partes = re.split(r'\s*[,;\t]\s*', linha, maxsplit=1)
    if len(partes) == 2:
        return partes[0], partes[1]
    m = RE_TELEFONE_NO_FIM.match(linha)
    return (m['nome'], m['tel']) if m else (linha, '')


class EquipeView(PermissionRequiredMixin, View):
    """Cadastro dos repórteres e entrega do acesso (QR, link, WhatsApp). Só administradores."""

    permission_required = ('boletins.add_dispositivo', 'boletins.change_dispositivo')
    login_url = reverse_lazy('admin:login')
    template_name = 'boletins/equipe.html'

    def get(self, request, form=None, status=200):
        agora = timezone.now()
        reporteres = list(Dispositivo.objects.annotate(qtd=Count('boletim')).order_by('-ativo', 'nome'))
        for d in reporteres:
            d.situacao, d.situacao_texto = situacao_reporter(d, agora)
            d.link = link_configuracao(request, d)
            d.whatsapp = link_whatsapp(d, d.link)
            d.telefone_legivel = telefone_legivel(d.telefone)
        ativos = [d for d in reporteres if d.ativo]
        entregar = request.GET.get('entregar', '')
        return render(request, self.template_name, {
            'reporteres': reporteres,
            'total_ativos': len(ativos),
            'total_prontos': sum(d.situacao in ('pronto', 'enviando') for d in ativos),
            'total_aguardando': sum(d.situacao == 'aguardando' for d in ativos),
            'entregar': int(entregar) if entregar.isdigit() else None,
            'form': form or {},
        }, status=status)

    def post(self, request):
        acao = request.POST.get('acao')
        if acao == 'criar':
            return self._criar(request)
        if acao == 'lote':
            return self._lote(request)
        pk = request.POST.get('id', '')
        d = get_object_or_404(Dispositivo, pk=int(pk) if pk.isdigit() else 0)
        if acao == 'editar':
            nome = request.POST.get('nome', '').strip()[:100]
            try:
                telefone = normalizar_telefone(request.POST.get('telefone'))
            except ValueError:
                messages.error(request, f'WhatsApp de {d.nome} não foi alterado: use o DDD e o número, como (43) 99999-1234.')
                return self._voltar()
            if not nome:
                messages.error(request, 'O nome do repórter não pode ficar vazio.')
                return self._voltar()
            d.nome, d.telefone = nome, telefone
            d.save(update_fields=['nome', 'telefone'])
            messages.success(request, f'Dados de {d.nome} salvos.')
        elif acao in ('desativar', 'reativar'):
            d.ativo = acao == 'reativar'
            d.save(update_fields=['ativo'])
            messages.success(request, f'{d.nome} pode enviar boletins de novo.' if d.ativo else
                             f'Acesso de {d.nome} desativado. O celular dele não envia mais boletins.')
        elif acao == 'novo_codigo':
            d.token = gerar_token()
            d.save(update_fields=['token'])
            messages.success(request, f'Novo código gerado. O link antigo de {d.nome} parou de funcionar: '
                                      'entregue o novo acesso abaixo.')
            return self._voltar(entregar=d.pk)
        return self._voltar()

    def _voltar(self, entregar=None):
        return HttpResponseRedirect(reverse('equipe') + (f'?entregar={entregar}' if entregar else ''))

    def _criar(self, request):
        nome = request.POST.get('nome', '').strip()[:100]
        form = {'nome': nome, 'telefone': request.POST.get('telefone', '').strip()}
        erros = {}
        if not nome:
            erros['nome'] = 'Escreva o nome do repórter.'
        elif Dispositivo.objects.filter(nome__iexact=nome, ativo=True).exists():
            erros['nome'] = 'Já existe um repórter ativo com esse nome. Acrescente a região, como "Maria — Zona 58".'
        try:
            telefone = normalizar_telefone(form['telefone'])
        except ValueError:
            erros['telefone'] = 'Use o DDD e o número, como (43) 99999-1234. Pode deixar em branco.'
        if erros:
            return self.get(request, form={**form, 'erros': erros}, status=400)
        d = Dispositivo.objects.create(nome=nome, telefone=telefone)
        messages.success(request, f'{d.nome} cadastrado. Agora entregue o acesso.')
        return self._voltar(entregar=d.pk)

    def _lote(self, request):
        criados, problemas = [], []
        existentes = {n.lower() for n in Dispositivo.objects.filter(ativo=True).values_list('nome', flat=True)}
        for linha in request.POST.get('lista', '').splitlines():
            linha = linha.strip()
            if not linha:
                continue
            nome, tel = ler_linha_lote(linha)
            nome = nome.strip()[:100]
            if not nome:
                problemas.append(f'"{linha}": falta o nome')
                continue
            try:
                telefone = normalizar_telefone(tel)
            except ValueError:
                problemas.append(f'"{linha}": WhatsApp fora do padrão')
                continue
            if nome.lower() in existentes:
                problemas.append(f'"{nome}": já cadastrado')
                continue
            existentes.add(nome.lower())
            criados.append(Dispositivo.objects.create(nome=nome, telefone=telefone))
        if criados:
            messages.success(request, f'{len(criados)} repórter(es) cadastrado(s). Use "Entregar acesso" em cada um.')
        if problemas:
            messages.warning(request, 'Não cadastrados: ' + '; '.join(problemas[:20]) + '.')
        if not criados and not problemas:
            messages.warning(request, 'A lista estava vazia. Escreva um repórter por linha.')
        return self._voltar()


class EquipeQrView(PermissionRequiredMixin, View):
    """QR Code de configuração de um repórter, em SVG, para escanear da tela."""

    permission_required = ('boletins.add_dispositivo', 'boletins.change_dispositivo')
    login_url = reverse_lazy('admin:login')

    def get(self, request, pk):
        d = get_object_or_404(Dispositivo, pk=pk, ativo=True)
        buf = io.BytesIO()
        segno.make(link_configuracao(request, d), error='m').save(buf, kind='svg', scale=8, border=2,
                                                                   xmldecl=False, dark='#0f1b2d')
        resp = HttpResponse(buf.getvalue(), content_type='image/svg+xml')
        resp['Cache-Control'] = 'no-store'  # o QR leva o código: não fica em cache
        return resp


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
