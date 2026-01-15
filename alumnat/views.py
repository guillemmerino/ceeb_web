from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView
from .models import SeguimentAlumnat
from .forms import SeguimentAlumnatForm
from django.views.generic import DeleteView
from django.views.generic import FormView
from django.contrib import messages
from .forms import ImportExcelForm
from .services.importacio import importar_excel_seguiment
from django.shortcuts import get_object_or_404
from django.core.mail import EmailMessage
from .models import SeguimentAlumnat
from .forms import SendEmailForm
import os
import unicodedata

from .models import SeguimentAlumnat
from .forms import BulkPdfByFilenameEmailForm



class SeguimentDeleteView(DeleteView):
    model = SeguimentAlumnat
    template_name = "seguiment_confirm_delete.html"
    success_url = reverse_lazy('seguiment_list')

class SeguimentListView(ListView):
    model = SeguimentAlumnat
    template_name = "seguiment.html"
    context_object_name = "records"
    paginate_by = 10  # default per-page; can be overridden via GET `per_page`

    def get_queryset(self):
        qs = super().get_queryset().order_by("-id")
        q = self.request.GET.get("q")
        camp = self.request.GET.get("camp")
        valor = self.request.GET.get("valor")
        if q:
            qs = qs.filter(nom_i_cognom__icontains=q)
        # Cerca avançada per camp específic
        if camp and valor:
            allowed = ["document", "correu", "sexe", "estat", "ropec", "bc", "cj", "cg", "pa", "mdp"]
            if camp in allowed:
                filter_kwargs = {f"{camp}__icontains": valor}
                qs = qs.filter(**filter_kwargs)
        return qs

    def get_paginate_by(self, queryset):
        # Si cerca per nom (q) o cerca avançada, sense límit (no paginar)
        q = self.request.GET.get('q')
        camp = self.request.GET.get('camp')
        valor = self.request.GET.get('valor')
        if q or (camp and valor):
            return None
        # allow user to control page size via `per_page` GET parameter
        try:
            per_page = int(self.request.GET.get('per_page', self.paginate_by))
            if per_page <= 0:
                return self.paginate_by
            return per_page
        except (TypeError, ValueError):
            return self.paginate_by


def seguiment_ajax(request):
    """JSON endpoint to return a page of `SeguimentAlumnat` for async loading."""
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    from django.http import JsonResponse
    from django.urls import reverse

    qs = SeguimentAlumnat.objects.all().order_by('-id')
    q = request.GET.get('q')
    if q:
        qs = qs.filter(nom_i_cognom__icontains=q)

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10

    paginator = Paginator(qs, per_page)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        return JsonResponse({'records': [], 'has_next': False})

    records = []
    for obj in page_obj.object_list:
        records.append({
            'id': obj.id,
            'nom_i_cognom': obj.nom_i_cognom or '-',
            'document': obj.document or '-',
            'correu': obj.correu or '-',
            'sexe': obj.sexe or '-',
            'data_naixement': obj.data_naixement.strftime('%d/%m/%Y') if obj.data_naixement else '-',
            'bc': obj.bc if obj.bc is not None and obj.bc != '' else '-',
            'cj': obj.cj if obj.cj is not None and obj.cj != '' else '-',
            'cg': obj.cg if obj.cg is not None and obj.cg != '' else '-',
            'pa': obj.pa if obj.pa is not None and obj.pa != '' else '-',
            'mdp': obj.mdp if obj.mdp is not None and obj.mdp != '' else '-',
            'ropec': obj.ropec if obj.ropec is not None and obj.ropec != '' else '-',
            'estat': obj.estat or '-',
            'edit_url': reverse('seguiment_update', args=[obj.id]),
        })

    return JsonResponse({
        'records': records,
        'has_next': page_obj.has_next(),
        'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
    })

class SeguimentCreateView(CreateView):
    model = SeguimentAlumnat
    form_class = SeguimentAlumnatForm
    template_name = "seguiment_form.html"
    success_url = reverse_lazy("seguiment_list")

class SeguimentUpdateView(UpdateView):
    model = SeguimentAlumnat
    form_class = SeguimentAlumnatForm
    template_name = "seguiment_form.html"
    success_url = reverse_lazy("seguiment_list")



class SeguimentImportExcelView(FormView):
    template_name = "seguiment_import.html"
    form_class = ImportExcelForm
    success_url = reverse_lazy("seguiment_list")

    def form_valid(self, form):
        fitxer = form.cleaned_data["fitxer"]
        sheet = form.cleaned_data["sheet"]

        result = importar_excel_seguiment(fitxer, sheet)

        if result.errors:
            messages.warning(self.request, "Importació feta amb avisos.")
            for err in result.errors[:10]:
                messages.error(self.request, err)

        messages.success(
            self.request,
            f"Fulls: {', '.join(result.fulls_processats)} | " f"Creats: {result.creats} | "
            f"Actualitzats: {result.actualitzats} | " f"No trobats: {result.no_trobats} | "
            f"Sense canvis: {result.ignorats} | Ignorats: {result.no_trobats}"
        )
        return super().form_valid(form)
    




class SeguimentSendEmailView(FormView):
    template_name = "seguiment_send_email.html"
    form_class = SendEmailForm
    success_url = reverse_lazy("seguiment_list")

    def dispatch(self, request, *args, **kwargs):
        self.alumne = get_object_or_404(SeguimentAlumnat, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        to_email = (self.alumne.correu or "").strip()

        if not to_email:
            messages.error(self.request, "Aquest registre no té correu informat.")
            return self.form_invalid(form)

        subject = form.cleaned_data["subject"]
        message = form.cleaned_data["message"]

        email = EmailMessage(
            subject=subject,
            body=message,
            to=[to_email],
        )

        try:
            # Afegir adjunts (si n'hi ha)
            for f in self.request.FILES.getlist("attachments"):
                # f.name, f.read(), f.content_type
                email.attach(f.name, f.read(), f.content_type)
            
            email.send(fail_silently=False)
            messages.success(self.request, f"Email enviat a {to_email}.")
        except Exception as e:
            messages.error(self.request, f"No s'ha pogut enviar l'email: {e}")

        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["alumne"] = self.alumne
        return ctx


def _norm(s: str) -> str:
    if not s:
        return ""
    s = s.strip().replace("_", " ")
    s = "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )
    s = " ".join(s.split())
    return s.upper()


def _name_from_filename(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]  # sense .pdf
    # Treu prefixos típics
    for prefix in ("Certificado_", "Certificat_", "Certificado-", "Certificat-"):
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    return _norm(base)


def _find_alumne_by_filename(filename: str):
    full_name = _name_from_filename(filename)  # "ALEX SALVANY CHORDA"
    if not full_name:
        return None, ""

    # 1) prova per nom_i_cognom
    alumne = SeguimentAlumnat.objects.filter(nom_i_cognom__iexact=full_name).first()
    if alumne:
        return alumne, full_name

    # 2) prova per (nom, cognom1, cognom2) si hi ha 3 tokens
    parts = full_name.split()
    if len(parts) >= 3:
        nom = parts[0]
        cognom1 = parts[1]
        cognom2 = " ".join(parts[2:])  # per si cognom2 és compost
        alumne = SeguimentAlumnat.objects.filter(
            nom__iexact=nom,
            cognom1__iexact=cognom1,
            cognom2__iexact=cognom2,
        ).first()
        if alumne:
            return alumne, full_name

    # 3) fallback (menys estricte)
    alumne = SeguimentAlumnat.objects.filter(nom_i_cognom__icontains=full_name).first()
    return alumne, full_name


class SeguimentSendBulkPdfsView(FormView):
    template_name = "seguiment_send_bulk_pdfs.html"
    form_class = BulkPdfByFilenameEmailForm
    success_url = reverse_lazy("seguiment_list")  # ajusta al teu nom de ruta

    def form_valid(self, form):
        subject = form.cleaned_data["subject"]
        message = form.cleaned_data["message"]

        files = self.request.FILES.getlist("certificates")
        if not files:
            messages.error(self.request, "No has adjuntat cap PDF.")
            return self.form_invalid(form)

        enviats = 0
        sense_match = 0
        sense_correu = 0
        errors = 0

        for f in files:
            alumne, full_name = _find_alumne_by_filename(f.name)

            if not alumne:
                sense_match += 1
                continue

            to_email = (alumne.correu or "").strip()
            if not to_email:
                sense_correu += 1
                continue

            email = EmailMessage(subject=subject, body=message, to=[to_email])
            email.attach(f.name, f.read(), f.content_type or "application/pdf")

            try:
                email.send(fail_silently=False)
                enviats += 1
            except Exception:
                errors += 1

            messages.success(
            self.request,
            f"Enviats: {enviats} | Sense alumne: {sense_match} | Sense correu: {sense_correu} | Errors: {errors}"
        )
        messages.info(self.request, f"Enviats: {enviats} | Sense alumne: {sense_match} | Sense correu: {sense_correu} | Errors: {errors}")
        return super().form_valid(form)
