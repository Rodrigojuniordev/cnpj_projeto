# -*- coding: utf-8 -*-
from sqlalchemy import create_engine, text
from config import DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME


class Banco:
    """Wrapper de conexao com o MySQL."""

    def __init__(self):
        url = (
            f"mysql+pymysql://{DB_USER}:{DB_PASS}@"
            f"{DB_HOST}:{DB_PORT}/{DB_NAME}?local_infile=1"
        )
        self.engine = create_engine(url)

    def executar(self, sql):
        """Executa uma query e retorna True/False."""
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql))
            return True
        except Exception as e:
            print("Erro:", e)
            return False

    def testar(self):
        """Testa se o banco esta acessivel."""
        return self.executar("SELECT 1")

    def configurar_sessao(self):
        """Ajusta a sessao para importacao em massa."""
        self.executar("SET SESSION sql_mode = ''")
        self.executar("SET SESSION unique_checks = 0")
        self.executar("SET SESSION foreign_key_checks = 0")

    def restaurar_sessao(self):
        """Restaura as verificacoes apos a carga."""
        self.executar("SET foreign_key_checks = 1")
        self.executar("SET unique_checks = 1")

    def limpar_staging(self):
        """Limpa todas as tabelas de staging."""
        for tabela in [
            "empresas_staging",
            "estabelecimentos_staging",
            "socios_staging",
            "simples_staging",
        ]:
            self.executar(f"TRUNCATE TABLE {tabela}")
