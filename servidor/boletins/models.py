import secrets

from django.db import models


def gerar_token():
    return secrets.token_urlsafe(18)


class Eleicao(models.Model):
    """Criada automaticamente no primeiro boletim de cada pleito/turno."""

    pleito = models.CharField('pleito (PLEI)', max_length=10)
    turno = models.PositiveSmallIntegerField()
    data = models.CharField('data (AAAAMMDD)', max_length=8, blank=True)
    abrangencia = models.CharField(max_length=10, choices=[('geral', 'Geral'), ('municipal', 'Municipal')], blank=True)
    ano = models.PositiveSmallIntegerField(null=True, blank=True)
    ativa = models.BooleanField('eleição em acompanhamento', default=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'eleição'
        verbose_name_plural = 'eleições'
        unique_together = [('pleito', 'turno')]
        ordering = ['-criada_em']

    def __str__(self):
        d = self.data
        data = f'{d[6:8]}/{d[4:6]}/{d[:4]}' if len(d) == 8 else '?'
        return f'Eleição {self.abrangencia or ""} {self.turno}º turno — {data} (pleito {self.pleito})'


class Dispositivo(models.Model):
    """Celular (ou equipe) autorizado a enviar boletins."""

    nome = models.CharField('repórter / equipe', max_length=100)
    token = models.CharField('código de acesso', max_length=40, unique=True, default=gerar_token)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    ultimo_envio = models.DateTimeField('último envio', null=True, blank=True)

    class Meta:
        verbose_name = 'celular autorizado'
        verbose_name_plural = 'celulares autorizados'

    def __str__(self):
        return self.nome


class Boletim(models.Model):
    ASSINATURA = [
        ('valida', 'Válida'),
        ('sem_certificado', 'Sem certificado'),
    ]

    eleicao = models.ForeignKey(Eleicao, on_delete=models.PROTECT, related_name='boletins')
    chave = models.CharField(max_length=60, unique=True)
    uf = models.CharField(max_length=2)
    municipio_tse = models.CharField('município (código TSE)', max_length=6)
    zona = models.PositiveIntegerField()
    secao = models.PositiveIntegerField('seção')
    local = models.CharField('local de votação', max_length=8, blank=True)
    urna = models.CharField(max_length=12, blank=True)
    aptos = models.PositiveIntegerField(default=0)
    comparecimento = models.PositiveIntegerField(default=0)
    oficial = models.BooleanField(default=True, help_text='Falso para boletins simulados ou de treinamento')
    assinatura = models.CharField(max_length=20, choices=ASSINATURA)
    tem_avisos = models.BooleanField('somas divergentes', default=False)
    dados = models.JSONField(help_text='Boletim interpretado (cargos e votos)')
    qrcodes = models.JSONField(help_text='Texto bruto dos QR Codes, como lidos')
    dispositivo = models.ForeignKey(Dispositivo, on_delete=models.SET_NULL, null=True, blank=True)
    reporter = models.CharField(max_length=100, blank=True)
    lido_em = models.DateTimeField(null=True, blank=True)
    recebido_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'boletins'
        ordering = ['-recebido_em']
        indexes = [models.Index(fields=['eleicao', 'uf', 'municipio_tse'])]

    def __str__(self):
        return f'{self.uf} {self.municipio_tse} · Zona {self.zona} · Seção {self.secao}'


class Candidato(models.Model):
    """Base de candidatos do TSE (consulta_cand). ue = BR, UF ou código do município."""

    ano = models.PositiveSmallIntegerField()
    ue = models.CharField('unidade eleitoral', max_length=6)
    cargo = models.PositiveSmallIntegerField()
    numero = models.PositiveIntegerField()
    nome_urna = models.CharField(max_length=120)
    partido = models.CharField(max_length=20, blank=True)
    situacao = models.CharField(max_length=60, blank=True)
    turno = models.PositiveSmallIntegerField(default=1)

    class Meta:
        unique_together = [('ano', 'ue', 'cargo', 'numero')]
        indexes = [models.Index(fields=['ano', 'ue'])]

    def __str__(self):
        return f'{self.nome_urna} ({self.numero} · {self.partido})'


class Partido(models.Model):
    ano = models.PositiveSmallIntegerField()
    numero = models.PositiveSmallIntegerField()
    sigla = models.CharField(max_length=20)
    nome = models.CharField(max_length=120, blank=True)

    class Meta:
        unique_together = [('ano', 'numero')]

    def __str__(self):
        return f'{self.numero} {self.sigla}'


class LocalVotacao(models.Model):
    """Escola/local de votação (TSE eleitorado_local_votacao): nome e quantas urnas esperar."""

    ano = models.PositiveSmallIntegerField()
    uf = models.CharField(max_length=2)
    municipio_tse = models.CharField(max_length=6)
    zona = models.PositiveIntegerField()
    numero = models.CharField('número do local', max_length=8)
    nome = models.CharField(max_length=150)
    endereco = models.CharField(max_length=200, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    secoes = models.PositiveIntegerField('urnas (seções)', default=0)
    eleitores = models.PositiveIntegerField(default=0)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = 'local de votação'
        verbose_name_plural = 'locais de votação'
        unique_together = [('ano', 'municipio_tse', 'zona', 'numero')]

    def __str__(self):
        return f'{self.nome} (zona {self.zona}, {self.secoes} urnas)'


class Municipio(models.Model):
    """Código TSE ↔ nome e código IBGE (para mapas)."""

    codigo_tse = models.CharField(max_length=6, unique=True)
    nome = models.CharField(max_length=80)
    uf = models.CharField(max_length=2)
    codigo_ibge = models.CharField(max_length=7, blank=True)

    class Meta:
        verbose_name = 'município'
        verbose_name_plural = 'municípios'

    def __str__(self):
        return f'{self.nome}/{self.uf}'
