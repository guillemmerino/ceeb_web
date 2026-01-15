
from django import forms
from .models import Competicio, Inscripcio

class CompeticioForm(forms.ModelForm):
    class Meta:
        model = Competicio
        fields = ['nom', 'data']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
        }

class ImportInscripcionsExcelForm(forms.Form):
    fitxer = forms.FileField()
    sheet = forms.CharField(required=False, help_text="Nom del full (opcional)")



class InscripcioForm(forms.ModelForm):
    # Opcions fixes per `categoria` i `subcategoria`
    PARTITS_NIVEL_ORDER = [
        "SÈNIOR", "JÚNIOR", 'JUVENIL', "CADET", "INFANTIL",
        "PREINFANTIL", "ALEVÍ", "PREALEVÍ", "BENJAMÍ", "PREBENJAMÍ",
        "MENUDETS", "MENUTS",
    ]

    SEXE_CHOICES = ["MASCULÍ", "FEMENÍ"]

    categoria = forms.ChoiceField(
        choices=[("", "---")] + [(v, v) for v in PARTITS_NIVEL_ORDER],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Categoria",
    )

    subcategoria = forms.ChoiceField(
        choices=[("", "---")] + [(v, v) for v in SEXE_CHOICES],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Subcategoria",
    )

    class Meta:
        model = Inscripcio
        fields = [
            "nom_i_cognoms",
            "document",
            "sexe",
            "data_naixement",
            "entitat",
            "categoria",
            "subcategoria",
            "grup",
        ]
