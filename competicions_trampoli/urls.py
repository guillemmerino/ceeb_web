from django.urls import path
from .views import CompeticioCreateView, CompeticioDeleteView, CompeticioHomeView, CompeticioListView, InscripcionsImportExcelView, InscripcionsListView
from competicions_trampoli import views


urlpatterns = [
    path("competicions/nova/", CompeticioCreateView.as_view(), name="create"),
    path("competicions/<int:pk>/importar/", InscripcionsImportExcelView.as_view(), name="import"),
    path("competicions/created/", CompeticioListView.as_view(), name="created"),   
    path("competicions/<int:pk>/inscripcions/", InscripcionsListView.as_view(), name="inscripcions_list"),
    path("competicions/<int:pk>/delete/", CompeticioDeleteView.as_view(), name="delete"),   
    path("competicions/", CompeticioHomeView.as_view(), name="competicions_home"),
    path("competicio/<int:pk>/inscripcions/reorder/", views.inscripcions_reorder, name="inscripcions_reorder"),
    path("competicio/<int:pk>/inscripcio/<int:ins_id>/editar/", views.InscripcioUpdateView.as_view(), name="inscripcio_edit"),
    path("competicio/<int:pk>/inscripcio/<int:ins_id>/eliminar/", views.InscripcioDeleteView.as_view(), name="inscripcio_delete"),
    path("competicio/<int:pk>/inscripcio/nova/", views.InscripcioCreateView.as_view(), name="inscripcio_add"),

]
