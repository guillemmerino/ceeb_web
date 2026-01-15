from django.db import models

class SeguimentAlumnat(models.Model):
    nom_i_cognom = models.CharField(max_length=255, blank=True, null=True)
    cognom1 = models.CharField(max_length=120, blank=True, null=True)
    cognom2 = models.CharField(max_length=120, blank=True, null=True)
    nom = models.CharField(max_length=120, blank=True, null=True)

    document = models.CharField(max_length=32, blank=True, null=True)  # DNI/Passaport
    sexe = models.CharField(max_length=20, blank=True, null=True)
    data_naixement = models.DateField(blank=True, null=True)
    correu = models.EmailField(blank=True, null=True)

    bc = models.CharField(max_length=50, blank=True, null=True)
    cj = models.CharField(max_length=50, blank=True, null=True)
    cg = models.CharField(max_length=50, blank=True, null=True)
    pa = models.CharField(max_length=50, blank=True, null=True)
    mdp = models.CharField(max_length=50, blank=True, null=True)

    ropec = models.CharField(max_length=50, blank=True, null=True)
    estat = models.CharField(max_length=50, blank=True, null=True)
    notificacio = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "seguiment_alumnat"
        verbose_name = "Seguiment Alumnat"