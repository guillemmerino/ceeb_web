from django.core.management.base import BaseCommand
from django.db import transaction
import pandas as pd
from alumnat.models import SeguimentAlumnat
from datetime import datetime, date

def clean(v):
    if v is None or pd.isna(v):
        return None
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v

def clean_date(v):
    # Per DateField (ex: data_naixement)
    if v is None or pd.isna(v):
        return None
    if isinstance(v, pd.Timestamp):
        v = v.to_pydatetime()
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    # si ve com text
    dt = pd.to_datetime(v, dayfirst=True, errors="coerce")
    return None if pd.isna(dt) else dt.date()

class Command(BaseCommand):
    help = "Importa el full 'Seguiment' d'un Excel a la taula seguiment_alumnat"

    def add_arguments(self, parser):
        parser.add_argument("xlsx_path", type=str, help="Ruta al fitxer .xlsx dins del contenidor")
        parser.add_argument("--truncate", action="store_true", help="Esborra la taula abans d'importar")

    @transaction.atomic
    def handle(self, *args, **opts):
        xlsx_path = opts["xlsx_path"]

        df = pd.read_excel(xlsx_path, sheet_name="Seguiment")
        df = df.replace({pd.NaT: None})
        df = df.where(pd.notnull(df), None)

        if opts["truncate"]:
            SeguimentAlumnat.objects.all().delete()

        objs = []
        for _, r in df.iterrows():
            # Data naixement pot venir com datetime
            data_naix = clean_date(r.get("Data Naixement"))


            objs.append(
                SeguimentAlumnat(
                    nom_i_cognom=clean(r.get("Nom i cognom")),
                    cognom1=clean(r.get("Cognom1")),
                    cognom2=clean(r.get("Cognom2")),
                    nom=clean(r.get("Nom")),
                    document=clean(r.get("DNI | Passaport")),
                    sexe=clean(r.get("Sexe")),
                    data_naixement=data_naix,
                    correu=clean(r.get("Correu electrònic")),
                    bc=clean(r.get("BC")),
                    cj=clean(r.get("CJ")),
                    cg=clean(r.get("CG")),
                    pa=clean(r.get("PA")),
                    mdp=clean(r.get("MDP")),
                    ropec=clean(r.get("NºROPEC")),
                    estat=clean(r.get("ESTAT")),
                    notificacio=clean(r.get("Notificació")),
                )
            )

            

        SeguimentAlumnat.objects.bulk_create(objs, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f"Importades {len(objs)} files a seguiment_alumnat"))
