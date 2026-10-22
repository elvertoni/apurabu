import base64
import json

import segno
from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html, mark_safe

from .models import Boletim, Candidato, Dispositivo, Eleicao, LocalVotacao, Municipio, Partido, gerar_token


def link_configuracao(request, d):
    cfg = {'servidor': request.build_absolute_uri('/').rstrip('/'), 'token': d.token, 'reporter': d.nome}
    codigo = base64.urlsafe_b64encode(json.dumps(cfg).encode()).decode().rstrip('=')
    return request.build_absolute_uri(f'/app/#cfg={codigo}')


@admin.register(Dispositivo)
class DispositivoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'ativo', 'ultimo_envio', 'qtd_boletins']
    list_filter = ['ativo']
    readonly_fields = ['token', 'configurar_celular', 'criado_em', 'ultimo_envio']
    fields = ['nome', 'ativo', 'configurar_celular', 'token', 'criado_em', 'ultimo_envio']
    actions = ['trocar_codigo']

    def get_form(self, request, obj=None, **kwargs):
        self._request = request
        return super().get_form(request, obj, **kwargs)

    @admin.action(description='Gerar novo código de acesso (o código antigo para de funcionar)')
    def trocar_codigo(self, request, queryset):
        # troca o token mantendo o cadastro: os boletins já enviados continuam ligados ao celular
        for d in queryset:
            d.token = gerar_token()
            d.save(update_fields=['token'])
        self.message_user(request, f'{queryset.count()} código(s) trocado(s). Abra cada celular e mostre o novo '
                                   'QR Code de configuração ao repórter.', messages.SUCCESS)

    @admin.display(description='boletins enviados')
    def qtd_boletins(self, obj):
        return obj.boletim_set.count()

    @admin.display(description='Configurar o celular')
    def configurar_celular(self, obj):
        if not obj.pk:
            return 'Salve primeiro; o QR Code de configuração aparece aqui.'
        url = link_configuracao(self._request, obj)
        svg = segno.make(url, error='m').svg_inline(scale=4)
        return format_html(
            '<div style="background:#fff;display:inline-block;padding:8px">{}</div>'
            '<p>O repórter aponta a câmera do celular para este QR Code (ou abre o link abaixo). '
            'O app abre já configurado com o servidor e o código de acesso.</p>'
            '<p><a href="{}" target="_blank">{}</a></p>',
            mark_safe(svg), url, url[:80] + '…')


class EleicaoListaForm(forms.ModelForm):
    class Meta:
        model = Eleicao
        fields = ['ativa']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ativa'].widget.attrs['aria-label'] = f'Eleição em acompanhamento: {self.instance}'


@admin.register(Eleicao)
class EleicaoAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'ativa', 'qtd']
    list_editable = ['ativa']

    def get_changelist_form(self, request, **kwargs):
        return EleicaoListaForm

    @admin.display(description='boletins')
    def qtd(self, obj):
        return obj.boletins.count()


@admin.register(Boletim)
class BoletimAdmin(admin.ModelAdmin):
    list_display = ['secao', 'zona', 'municipio_tse', 'uf', 'local', 'comparecimento', 'assinatura',
                    'tem_avisos', 'oficial', 'reporter', 'recebido_em']
    list_filter = ['eleicao', 'uf', 'assinatura', 'tem_avisos', 'oficial', 'dispositivo']
    search_fields = ['chave', 'municipio_tse', 'urna']
    readonly_fields = [f.name for f in Boletim._meta.fields if f.name not in ('dados', 'qrcodes')] + ['resumo']
    exclude = ['dados', 'qrcodes']
    date_hierarchy = 'recebido_em'

    def has_add_permission(self, request):
        return False  # boletins só entram pelos QR Codes

    @admin.display(description='Votos')
    def resumo(self, obj):
        linhas = []
        for cg in obj.dados['cargos']:
            top = sorted(cg['candidatos'].items(), key=lambda x: -x[1])[:8]
            t = cg['totais']
            linhas.append(format_html(
                '<p><b>{}</b> — válidos {} · brancos {} · nulos {}<br>{}</p>',
                cg['cargo'], t.get('validos', 0), t.get('BRAN', 0), t.get('NULO', 0),
                ', '.join(f'{n}: {v}' for n, v in top)))
        return mark_safe(''.join(linhas))


@admin.register(Candidato)
class CandidatoAdmin(admin.ModelAdmin):
    list_display = ['numero', 'nome_urna', 'partido', 'cargo', 'ue', 'ano', 'situacao']
    list_filter = ['ano', 'cargo']
    search_fields = ['nome_urna', 'numero', 'ue']


admin.site.register(Partido)
admin.site.register(Municipio)


@admin.register(LocalVotacao)
class LocalVotacaoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'municipio_tse', 'zona', 'numero', 'secoes', 'eleitores', 'ano']
    list_filter = ['ano', 'uf']
    search_fields = ['nome', 'municipio_tse', 'bairro']
