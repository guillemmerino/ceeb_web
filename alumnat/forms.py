from django import forms
from .models import SeguimentAlumnat
from django.forms.widgets import ClearableFileInput

class SeguimentAlumnatForm(forms.ModelForm):
    class Meta:
        model = SeguimentAlumnat
        fields = [
            "nom_i_cognom", "cognom1", "cognom2", "nom",
            "document", "sexe", "data_naixement", "correu",
            "bc", "cj", "cg", "pa", "mdp",
            "ropec", "estat", "notificacio",
        ]


SHEET_CHOICES = [
    ("ALL", "Tots els fulls (BC, JOC i GIO)"),
    ("BC", "Només BC"),
    ("JOC", "Només JOC"),
    ("GIO", "Només GIO"),
]

class ImportExcelForm(forms.Form):
    fitxer = forms.FileField(label="Fitxer Excel")
    sheet = forms.ChoiceField(label="Quin full vols importar?", choices=SHEET_CHOICES)

    def clean_fitxer(self):
        f = self.cleaned_data["fitxer"]
        if not f.name.lower().endswith((".xlsx", ".xls")):
            raise forms.ValidationError("Puja un fitxer Excel (.xlsx o .xls).")
        return f



class SendEmailForm(forms.Form):
    subject = forms.CharField(label="Assumpte", max_length=200)
    message = forms.CharField(label="Missatge", widget=forms.Textarea)

    attachments = forms.FileField(
            label="Adjunts",
            required=False,
            widget=ClearableFileInput(attrs={"multiple": True})
        )
    


class BulkPdfByFilenameEmailForm(forms.Form):
    subject = forms.CharField(label="Assumpte", max_length=200)
    message = forms.CharField(label="Missatge", widget=forms.Textarea)

    certificates = forms.FileField(
        label="Certificats (PDF)",
        widget=ClearableFileInput(attrs={"multiple": True, "accept": "application/pdf"}),
    )
