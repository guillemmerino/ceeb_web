import io
from celery import shared_task
import requests
import os
import uuid
import httpx
import aiofiles
import asyncio
from django.conf import settings
import redis
import json

CERTIFICATS_API = os.getenv("CERTIFICATS_API", "http://certificats:8000/process-pdfs/")
CALENDARITZACIONS_API = os.getenv("CALENDARITZACIONS_API", "http://calendaritzacions:8000/process_async")
CALENDARITZACIONS_API_SEGONA_FASE = os.getenv("CALENDARITZACIONS_API_SEGONA_FASE", "http://calendaritzacions:8000/process_async_segona_fase/")
LLISTATS_PROVISIONALS_API = os.getenv("LLISTATS_PROVISIONALS_API", "http://natacio:8000/provisionals/")
LLISTATS_DEFINITIUS_API = os.getenv("LLISTATS_DEFINITIUS_API", "http://natacio:8000/definitius/")
DESIGNACIONS_API = os.getenv("DESIGNACIONS_API", "http://designacions:8000/process_designacions/")
MEDIA_URL = os.getenv("MEDIA_URL", "/media/")  # e.g., "/media/"
RESULTS_DIR = os.getenv("MEDIA_ROOT", "/data/media")  # e.g., "/data/media"


def _path_to_media_url(path: str) -> str | None:
    """If `path` is under RESULTS_DIR (or MEDIA_ROOT), return a media URL.
    Otherwise return None.
    """
    try:
        if not path:
            return None
        normalized = os.path.normpath(path)
        root = os.path.normpath(RESULTS_DIR)
        if normalized.startswith(root):
            rel = os.path.relpath(normalized, root).replace(os.sep, '/')
            return MEDIA_URL.rstrip('/') + '/' + rel
    except Exception:
        pass
    return None

# ---------------------------------------------------------------------------------------------------
# CERTIFICATS
# ---------------------------------------------------------------------------------------------------


@shared_task(bind=True, queue='heavy_queue')
def process_certificats_task(self, file_paths):
    """
    Tasca SÍNCRONA per a Celery (retorna un valor serialitzable),
    però que executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': ['Iniciant el procés...']})

    try:
        remote_job_id, zip_path = asyncio.run(_process_certificats_async(task_id, file_paths, _push(self)))

        # If the external service returned a remote job id, it may be
        # processing asynchronously. We must publish the correct Redis
        # key under the remote job id (not the Celery task id) so the
        # frontend or other services can poll `job:{remote_job_id}`.
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        try:
            r = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        except Exception:
            r = None

        # Case A: remote job id provided
        if remote_job_id:
            # If the remote service already produced a zip_path, mark as done
            if zip_path:
                # Persist remote job metadata under remote_job_id
                try:
                    if r:
                        result_url = _path_to_media_url(zip_path) or zip_path
                        job_meta = json.dumps({'status': 'done', 'result': zip_path, 'result_url': result_url, 'logs': []})
                        r.set(f"job:{remote_job_id}", job_meta)
                        r.expire(f"job:{remote_job_id}", 60 * 60 * 24 * 7)
                        try:
                            r.publish(f"logs:{remote_job_id}", json.dumps({'event': 'done', 'result': zip_path, 'result_url': zip_path}))
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    # Expose a URL to the frontend instead of filesystem path when possible
                    self.update_state(state='SUCCESS', meta={'logs': ['Procés complet (remot amb resultat).'], 'result': _path_to_media_url(zip_path) or zip_path})
                except Exception:
                    pass

                return remote_job_id

            # Otherwise the remote job is processing asynchronously: create a pending entry
            try:
                if r:
                    job_meta = json.dumps({'status': 'PENDING', 'logs': []})
                    r.set(f"job:{remote_job_id}", job_meta)
                    r.expire(f"job:{remote_job_id}", 60 * 60 * 24 * 7)
                    try:
                        r.publish(f"logs:{remote_job_id}", json.dumps({'event': 'created', 'remote_id': remote_job_id}))
                    except Exception:
                        pass
            except Exception:
                pass

            # Update Celery meta to expose the remote id so the frontend can poll
            try:
                self.update_state(state='SUCCESS', meta={'logs': ['Tasca encolada al servei remot.'], 'result': remote_job_id})
            except Exception:
                pass

            return remote_job_id

        # Case B: no remote id -> perhaps the external service returned a direct zip_path
        try:
            if zip_path:
                if r:
                    try:
                        result_url = _path_to_media_url(zip_path) or zip_path
                        job_meta = json.dumps({'status': 'done', 'result': zip_path, 'result_url': result_url, 'logs': []})
                        r.set(f"job:{task_id}", job_meta)
                        r.expire(f"job:{task_id}", 60 * 60 * 24 * 7)
                        try:
                            r.publish(f"logs:{task_id}", json.dumps({'event': 'done', 'result': zip_path, 'result_url': result_url}))
                        except Exception:
                            pass
                    except Exception:
                        pass

                try:
                    self.update_state(state='SUCCESS', meta={'logs': ['Procés complet.'], 'result': _path_to_media_url(zip_path) or zip_path})
                except Exception:
                    pass

                return _path_to_media_url(zip_path) or zip_path
        except Exception:
            pass

        # Fallback: nothing meaningful returned from external service
        try:
            self.update_state(state='SUCCESS', meta={'logs': ['Procés complet (sense resultat directe).'], 'result': None})
        except Exception:
            pass

        return None  # <- str serialitzable (or None)
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise


def _push(self_task):
    """Callback per reportar logs a Celery meta, sempre serialitzable."""
    def _inner(msg: str):
        try:
            print(f"Enviant log: {msg}")
            self_task.update_state(state='PROGRESS', meta={'logs': [str(msg)]})
            # També publiquem el missatge al canal Redis perquè l'SSE pugui llegir-lo
            try:
                task_id_local = str(self_task.request.id)
                redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
                r = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
                payload = json.dumps({'message': str(msg)})
                r.publish(f"logs:{task_id_local}", payload)
            except Exception:
                # No brownzeu la tasca per fallades en pub/sub
                pass
        except Exception:
            # Evita que cap problema de backend de resultats mati la tasca
            pass
    return _inner


async def _process_certificats_async(task_id: str, file_paths: list[str], push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    # 1) Prepara el multipart amb BYTES (evitem deixar handlers oberts)
    multipart = []
    for path in file_paths:
        filename = os.path.basename(path)
        with open(path, 'rb') as f:
            data = f.read()
        # httpx accepta bytes en el camp del fitxer
        multipart.append(('files', (filename, data, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')))

    headers = {"X-Task-ID": task_id}

    push('Enviant fitxers al servei extern...')
    async with httpx.AsyncClient(timeout=None) as client:
        resp = await client.post(CERTIFICATS_API, files=multipart, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"Error del servei de certificats ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')
        zip_path = data.get('zip_path')

    push('Processant resposta del servei...')
    
    
    push(f'Procés complet. Preparant enllaç de descàrrega...')
    return remote_job_id, zip_path


# ---------------------------------------------------------------------------------------------------
# CALENDARITZACIONS
# ---------------------------------------------------------------------------------------------------

@shared_task(bind=True, queue='heavy_queue')
def process_calendaritzacions_task(self, file_path: str):
    """
    Tasca SÍNCRONA per a Celery (retorna un valor serialitzable),
    però que executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': ['Iniciant el procés de calendaritzacions...']})

    try:
        result_url = asyncio.run(_process_calendaritzacions_async(task_id, file_path, _push(self)))
        return result_url  # <- str serialitzable
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise

async def _process_calendaritzacions_async(task_id: str, file_path: str, push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    headers = {"X-Task-ID": task_id}

    # Llegim el fitxer local i fem un POST multipart/form-data al servei FastAPI
    filename = os.path.basename(file_path)
    # Intenta inferir el content-type a partir de l'extensió per ajudar el servei remot
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.xlsx':
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        raise RuntimeError(f"Tipus de fitxer no suportat a calendaritzacions: {filename}. Ha de ser .xlsx")
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
    except Exception as e:
        raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

    push(f'Enviant ruta al servei extern de calendaritzacions... (filename={filename}, content_type={content_type})')
    async with httpx.AsyncClient(timeout=None) as client:
        # Send only the path string as JSON so the remote service can open the
        # file from the shared MEDIA directory. We also forward the X-Task-ID
        # header so the remote service can associate logs/results.
        resp = await client.post(
            CALENDARITZACIONS_API,
            json={"file_path": file_path},
            headers=headers,
            follow_redirects=True,
        )

    # Debug: publish status and body when unexpected to help troubleshooting
    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass

    # Expect the external service to accept the job and return a JSON with job_id
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Error del servei de calendaritzacions ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    # We don't poll or download here: the frontend will poll and read the file from MEDIA
    # Ensure the external service received the client task id (we sent X-Task-ID)
    if not remote_job_id:
        # If service didn't return job_id, still consider POST successful when 202/200
        remote_job_id = task_id

    push(f"Servei acceptat la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove the local temp file here: the remote service will open
    # the shared path and must be able to read it. Removing it immediately
    # caused `FileNotFoundError` in the remote worker when it tried to process.
    push(f"Left local temp file in place for remote processing: {file_path}")

    # Return the remote job id so the frontend (or Django) can poll the external service.
    return remote_job_id


@shared_task(bind=True, queue='heavy_queue')
def process_calendaritzacions_fase_dos_task(self, file_path: str):
    """
    Tasca SÍNCRONA per a Celery (retorna un valor serialitzable),
    però que executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': ['Iniciant el procés de calendaritzacions...']})

    try:
        result_url = asyncio.run(_process_calendaritzacions_fase_dos_async(task_id, file_path, _push(self)))
        return result_url  # <- str serialitzable
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise

async def _process_calendaritzacions_fase_dos_async(task_id: str, file_path: str, push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    headers = {"X-Task-ID": task_id}

    # Llegim el fitxer local i fem un POST multipart/form-data al servei FastAPI
    filename = os.path.basename(file_path)
    # Intenta inferir el content-type a partir de l'extensió per ajudar el servei remot
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.xlsx':
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        raise RuntimeError(f"Tipus de fitxer no suportat a calendaritzacions: {filename}. Ha de ser .xlsx")
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
    except Exception as e:
        raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

    push(f'Enviant ruta al servei extern de calendaritzacions... (filename={filename}, content_type={content_type})')
    async with httpx.AsyncClient(timeout=None) as client:
        # Send only the path string as JSON so the remote service can open the
        # file from the shared MEDIA directory. We also forward the X-Task-ID
        # header so the remote service can associate logs/results.
        resp = await client.post(
            CALENDARITZACIONS_API_SEGONA_FASE,
            json={"file_path": file_path},
            headers=headers,
            follow_redirects=True,
        )

    # Debug: publish status and body when unexpected to help troubleshooting
    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass

    # Expect the external service to accept the job and return a JSON with job_id
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Error del servei de calendaritzacions ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    # We don't poll or download here: the frontend will poll and read the file from MEDIA
    # Ensure the external service received the client task id (we sent X-Task-ID)
    if not remote_job_id:
        # If service didn't return job_id, still consider POST successful when 202/200
        remote_job_id = task_id

    push(f"Servei acceptat la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove the local temp file here: the remote service will open
    # the shared path and must be able to read it. Removing it immediately
    # caused `FileNotFoundError` in the remote worker when it tried to process.
    push(f"Left local temp file in place for remote processing: {file_path}")

    # Return the remote job id so the frontend (or Django) can poll the external service.
    return remote_job_id


# ---------------------------------------------------------------------------------------------------
# DESIGNACIONS
# ---------------------------------------------------------------------------------------------------

@shared_task(bind=True, queue='heavy_queue')
def process_designacions_task(self, file_paths):
    """
    Tasca SÍNCRONA per a Celery que accepta una ruta o una llista de rutes.
    Executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    print(f"process_designacions_task: file_paths={file_paths}")
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': [f'Iniciant el procés de designacions...{file_paths}']})

    try:
        result = asyncio.run(_process_designacions_async(task_id, file_paths, _push(self)))
        return result  # <- str serialitzable (remote job id or url)
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise


async def _process_designacions_async(task_id: str, file_paths, push):
    """
    Nucli ASÍNCRON: accepta una ruta o una llista de rutes, fa la crida HTTP
    al servei de designacions i retorna el `job_id` remot (o el task_id si
    el servei no en retorna).
    """
    headers = {"X-Task-ID": task_id}

    # Normalize to list
    if isinstance(file_paths, (str, bytes)):
        paths = [file_paths]
    elif file_paths is None:
        paths = []
    else:
        paths = list(file_paths)

    if not paths:
        raise RuntimeError("No hi ha cap fitxer per processar a designacions.")

    # Build multipart payload with multiple files
    multipart = []
    for path in paths:
        filename = os.path.basename(path)
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.xlsx':
            content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            
            raise RuntimeError(f"Tipus de fitxer no suportat a designacions: {filename}. Ha de ser .xlsx")

        try:
            with open(path, 'rb') as f:
                file_bytes = f.read()
        except Exception as e:
            raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

        # Use the same 'files' field name as other endpoints that accept multiple files
        multipart.append(('files', (filename, file_bytes, content_type)))

    push('Enviant fitxers al servei de designacions...')
    print(f"Sending to DESIGNACIONS_API={DESIGNACIONS_API} with headers={headers} and {len(multipart)} files.")
    async with httpx.AsyncClient(timeout=None) as client:
        # Follow redirects (307/308) so POST-preserving redirects are handled
        resp = await client.post(DESIGNACIONS_API, files=multipart, headers=headers, follow_redirects=True)

    # Log redirect history for debugging
    try:
        history = getattr(resp, 'history', None)
        if history:
            push(f"Redirect history: {[{'status': r.status_code, 'url': str(r.url)} for r in history]}")
    except Exception:
        pass

    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass
        raise RuntimeError(f"Error del servei de designacions ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    if not remote_job_id:
        remote_job_id = task_id

    push(f"Servei acceptat a la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove local temp files: remote worker may need them (shared MEDIA dir)
    for p in paths:
        push(f"Left local temp file in place for remote processing: {p}")

    return remote_job_id


# ---------------------------------------------------------------------------------------------------
# LLISTATS PROVISIONALS
# ---------------------------------------------------------------------------------------------------
@shared_task(bind=True, queue='heavy_queue')
def process_llistats_provisionals_task(self, file_path):
    """
    Tasca SÍNCRONA per a Celery que accepta una ruta o una llista de rutes.
    Executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    print(f"process_llistats_provisionals_task: file_path={file_path}")
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': [f'Iniciant el procés de llistats provisionals...{file_path}']})

    try:
        result = asyncio.run(_process_llistats_provisionals_async(task_id, file_path, _push(self)))
        return result  # <- str serialitzable (remote job id or url)
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise


async def _process_llistats_provisionals_async(task_id: str, file_path: str, push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    headers = {"X-Task-ID": task_id}

    # Llegim el fitxer local i fem un POST multipart/form-data al servei FastAPI
    filename = os.path.basename(file_path)
    # Intenta inferir el content-type a partir de l'extensió per ajudar el servei remot
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.xlsx':
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        raise RuntimeError(f"Tipus de fitxer no suportat: {filename}. Ha de ser .xlsx")
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
    except Exception as e:
        raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

    push(f'Enviant ruta al servei extern... (filename={filename}, content_type={content_type})')
    async with httpx.AsyncClient(timeout=None) as client:
        # Send only the path string as JSON so the remote service can open the
        # file from the shared MEDIA directory. We also forward the X-Task-ID
        # header so the remote service can associate logs/results.
        resp = await client.post(
            LLISTATS_PROVISIONALS_API,
            json={"file_path": file_path},
            headers=headers, follow_redirects=True
        )

    # Debug: publish status and body when unexpected to help troubleshooting
    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass

    # Expect the external service to accept the job and return a JSON with job_id
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Error del servei de llistats ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    # We don't poll or download here: the frontend will poll and read the file from MEDIA
    # Ensure the external service received the client task id (we sent X-Task-ID)
    if not remote_job_id:
        # If service didn't return job_id, still consider POST successful when 202/200
        remote_job_id = task_id

    push(f"Servei acceptat la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove the local temp file here: the remote service will open
    # the shared path and must be able to read it. Removing it immediately
    # caused `FileNotFoundError` in the remote worker when it tried to process.
    push(f"Left local temp file in place for remote processing: {file_path}")

    # Return the remote job id so the frontend (or Django) can poll the external service.
    return remote_job_id


# ---------------------------------------------------------------------------------------------------
# LLISTATS DEFINITIUS
# ---------------------------------------------------------------------------------------------------
@shared_task(bind=True, queue='heavy_queue')
def process_llistats_definitius_task(self, file_path):
    """
    Tasca SÍNCRONA per a Celery que accepta una ruta o una llista de rutes.
    Executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    print(f"process_llistats_provisionals_task: file_path={file_path}")
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': [f'Iniciant el procés de llistats provisionals...{file_path}']})

    try:
        result = asyncio.run(_process_llistats_definitius_async(task_id, file_path, _push(self)))
        return result  # <- str serialitzable (remote job id or url)
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise


async def _process_llistats_definitius_async(task_id: str, file_path: str, push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    headers = {"X-Task-ID": task_id}

    # Llegim el fitxer local i fem un POST multipart/form-data al servei FastAPI
    filename = os.path.basename(file_path)
    # Intenta inferir el content-type a partir de l'extensió per ajudar el servei remot
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.xlsx':
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        raise RuntimeError(f"Tipus de fitxer no suportat: {filename}. Ha de ser .xlsx")
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
    except Exception as e:
        raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

    push(f'Enviant ruta al servei extern... (filename={filename}, content_type={content_type})')
    async with httpx.AsyncClient(timeout=None) as client:
        # Send only the path string as JSON so the remote service can open the
        # file from the shared MEDIA directory. We also forward the X-Task-ID
        # header so the remote service can associate logs/results.
        resp = await client.post(
            LLISTATS_DEFINITIUS_API,
            json={"file_path": file_path},
            headers=headers, follow_redirects=True
        )

    # Debug: publish status and body when unexpected to help troubleshooting
    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass

    # Expect the external service to accept the job and return a JSON with job_id
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Error del servei de llistats ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    # We don't poll or download here: the frontend will poll and read the file from MEDIA
    # Ensure the external service received the client task id (we sent X-Task-ID)
    if not remote_job_id:
        # If service didn't return job_id, still consider POST successful when 202/200
        remote_job_id = task_id

    push(f"Servei acceptat la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove the local temp file here: the remote service will open
    # the shared path and must be able to read it. Removing it immediately
    # caused `FileNotFoundError` in the remote worker when it tried to process.
    push(f"Left local temp file in place for remote processing: {file_path}")

    # Return the remote job id so the frontend (or Django) can poll the external service.
    return remote_job_id
