from django.contrib import admin
from django.urls import path, re_path
from django.views.generic import TemplateView

from boletins import views

admin.site.site_header = 'Apura BU — servidor da rádio'
admin.site.site_title = 'Apura BU'
admin.site.index_title = 'Apuração extraoficial'
admin.site.site_url = '/painel/'  # link "Ver o site" do admin abre o painel

urlpatterns = [
    path('', views.raiz),
    path('admin/', admin.site.urls),
    path('painel/', views.PainelView.as_view(), name='painel'),
    path('painel/dados/', views.PainelDadosView.as_view(), name='painel-dados'),
    # manual da equipe: página aberta, sem login (não traz senhas nem dados do servidor)
    path('manual/', TemplateView.as_view(template_name='boletins/manual.html'), name='manual'),
    path('api/ping/', views.PingView.as_view(), name='ping'),
    path('api/boletins/', views.BoletimView.as_view(), name='boletins'),
    path('api/nomes/', views.NomesView.as_view(), name='nomes'),
    path('api/totais/', views.TotaisView.as_view(), name='totais'),
    path('importar/', views.ImportarView.as_view(), name='importar'),
    path('equipe/', views.EquipeView.as_view(), name='equipe'),
    path('equipe/<int:pk>/qr.svg', views.EquipeQrView.as_view(), name='equipe-qr'),
    re_path(r'^app/(?P<caminho>.*)$', views.PwaView.as_view(), name='app'),
]
