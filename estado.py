# -*- coding: utf-8 -*-
import os
import json
import hashlib

from config import STATE, CHUNK


class Estado:
    """Controla os hashes (ETag ou MD5) por competencia."""

    def __init__(self, competencia):
        self.competencia = competencia
        os.makedirs(STATE, exist_ok=True)

    # ---------------- MD5 ----------------

    @staticmethod
    def md5(arquivo):
        h = hashlib.md5()
        try:
            with open(arquivo, "rb") as f:
                for bloco in iter(lambda: f.read(CHUNK), b""):
                    h.update(bloco)
            return h.hexdigest()
        except Exception as e:
            print("Erro MD5:", e)
            return None

    # ---------------- Arquivo de hashes ----------------

    def _arquivo(self):
        return os.path.join(STATE, f"hashes_{self.competencia}.json")

    def carregar(self):
        try:
            with open(self._arquivo(), "r") as f:
                return json.load(f)
        except:
            return {}

    def salvar(self, hashes):
        with open(self._arquivo(), "w") as f:
            json.dump(hashes, f, indent=4)
