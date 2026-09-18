# -*- coding: utf-8 -*-
import os
import re
import time
import zipfile
import requests
import xml.etree.ElementTree as ET

from config import (
    TOKEN, URL_BASE, DOWNLOADS, TIMEOUT, CHUNK
)


class Receita:
    """Encapsula tudo que envolve acessar/baixar/extrair arquivos da Receita."""

    def __init__(self):
        os.makedirs(DOWNLOADS, exist_ok=True)

    # ---------------- Deteccao de competencia ----------------

    def detectar_competencia(self):
        """Descobre a pasta YYYY-MM mais recente no WebDAV."""
        url = f"{URL_BASE}/public.php/webdav/"
        print("Detectando competencia mais recente...")

        try:
            resposta = requests.request(
                "PROPFIND", url,
                auth=(TOKEN, ""),
                headers={"Depth": "1", "Content-Type": "application/xml"},
                timeout=30,
            )
            if resposta.status_code in [200, 207]:
                root = ET.fromstring(resposta.content)
                competencias = []

                for href in root.findall(".//{DAV:}href"):
                    link = href.text
                    if not link:
                        continue
                    partes = link.rstrip("/").split("/")
                    ultimo = partes[-1] if partes else ""
                    if re.match(r"^\d{4}-\d{2}$", ultimo):
                        competencias.append(ultimo)

                if competencias:
                    competencias = sorted(set(competencias), reverse=True)
                    print("Competencia detectada:", competencias[0])
                    return competencias[0]

        except Exception as e:
            print("Falha deteccao:", e)

        return None

    # ---------------- Listagem ----------------

    def listar(self, competencia):
        """Lista os arquivos .zip da competencia via WebDAV (fallback Nextcloud)."""
        arquivos = self._listar_webdav(competencia)
        if arquivos:
            return arquivos

        return self._listar_nextcloud(competencia)

    def _listar_webdav(self, competencia):
        url = f"{URL_BASE}/public.php/webdav/{competencia}"
        print("Listando arquivos...")

        try:
            resposta = requests.request(
                "PROPFIND", url,
                auth=(TOKEN, ""),
                headers={"Depth": "1", "Content-Type": "application/xml"},
                timeout=30,
            )
            if resposta.status_code in [200, 207]:
                root = ET.fromstring(resposta.content)
                arquivos = []

                for href in root.findall(".//{DAV:}href"):
                    link = href.text
                    if link and link.lower().endswith(".zip"):
                        if link.startswith("/"):
                            link = URL_BASE + link
                        arquivos.append(link)

                print("Arquivos encontrados:", len(arquivos))
                return arquivos

        except Exception as e:
            print("WebDAV falhou:", e)

        return []

    def _listar_nextcloud(self, competencia):
        print("Tentando Nextcloud...")
        url = f"{URL_BASE}/index.php/s/{TOKEN}?dir=/{competencia}"

        try:
            resposta = requests.get(url, timeout=30)
            resposta.raise_for_status()

            links = re.findall(r'href="([^"]*\.zip[^"]*)"', resposta.text)
            arquivos = []

            for link in links:
                if link.startswith("/"):
                    link = URL_BASE + link
                arquivos.append(link)

            print("Arquivos encontrados:", len(arquivos))
            return arquivos

        except Exception as e:
            print("Nextcloud falhou:", e)
            return []

    # ---------------- ETag ----------------

    def obter_etag(self, url):
        """Consulta o ETag do arquivo sem baixa-lo."""
        try:
            resposta = requests.head(url, auth=(TOKEN, ""), timeout=30)
            if resposta.status_code == 200:
                etag = resposta.headers.get("ETag", "").strip('"')
                return etag or None
        except:
            pass
        return None

    # ---------------- Download ----------------

    def baixar(self, url, tentativas=3):
        """Baixa um arquivo com retry e verifica se e ZIP valido."""
        nome = os.path.basename(url)
        caminho = os.path.join(DOWNLOADS, nome)

        if os.path.exists(caminho) and zipfile.is_zipfile(caminho):
            return caminho

        for tentativa in range(1, tentativas + 1):
            print(f"Baixando {nome} (tentativa {tentativa}/{tentativas})...")

            try:
                resposta = requests.get(
                    url, auth=(TOKEN, ""),
                    stream=True, timeout=TIMEOUT,
                )
                resposta.raise_for_status()

                with open(caminho, "wb") as arquivo:
                    for bloco in resposta.iter_content(chunk_size=CHUNK):
                        if bloco:
                            arquivo.write(bloco)

                if not zipfile.is_zipfile(caminho):
                    print("ZIP invalido:", nome)
                    if os.path.exists(caminho):
                        os.remove(caminho)
                    return None

                print("Download OK")
                return caminho

            except Exception as e:
                print(f"  Falha: {e}")

                if os.path.exists(caminho):
                    try:
                        os.remove(caminho)
                    except:
                        pass

                if tentativa < tentativas:
                    print("  Aguardando 10s antes de tentar novamente...")
                    time.sleep(10)

        return None

    # ---------------- Extracao ----------------

    def extrair(self, zip_path):
        """Extrai o ZIP e devolve o caminho do primeiro arquivo nao vazio."""
        pasta = os.path.splitext(zip_path)[0]

        try:
            with zipfile.ZipFile(zip_path) as arquivo:
                arquivo.extractall(pasta)

            for raiz, _, arquivos in os.walk(pasta):
                for nome in arquivos:
                    caminho = os.path.join(raiz, nome)
                    if os.path.getsize(caminho) > 0:
                        return caminho

        except Exception as e:
            print("Erro extracao:", e)

        return None
