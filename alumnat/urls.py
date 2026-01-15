from django.urls import path
from .views import SeguimentImportExcelView, SeguimentListView, SeguimentCreateView, SeguimentSendBulkPdfsView 
from .views import SeguimentSendEmailView, SeguimentUpdateView, SeguimentDeleteView, seguiment_ajax

urlpatterns = [
    path("formacio/seguiment/", SeguimentListView.as_view(), name="seguiment_list"),
    path("formacio/seguiment/nou/", SeguimentCreateView.as_view(), name="seguiment_create"),
    path("formacio/seguiment/<int:pk>/editar/", SeguimentUpdateView.as_view(), name="seguiment_update"),
    path("formacio/seguiment/ajax/", seguiment_ajax, name="seguiment_ajax"),
    path("formacio/seguiment/<int:pk>/eliminar/", SeguimentDeleteView.as_view(), name="seguiment_delete"),
    path("formacio/seguiment/importar-excel/", SeguimentImportExcelView.as_view(), name="seguiment_import_excel"),
    path("formacio/seguiment/<int:pk>/email/", SeguimentSendEmailView.as_view(), name="seguiment_send_email"),
    path("formacio/seguiment/email-certificats/", SeguimentSendBulkPdfsView.as_view(), name="seguiment_send_email_certificates"),
]
