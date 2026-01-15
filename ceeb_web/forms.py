from django import forms

class CertificatsUploadForm(forms.Form):
    files = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"multiple": True}),
        label="Selecciona arxius PDF o ZIP",
        required=True,
    )
