# -*- coding: utf-8 -*-
import os

from config import COMPETENCIA, AUXILIARES, PRINCIPAIS
from banco import Banco
from receita import Receita
from estado import Estado
from importador import Importador


def identificar_tipo(nome):
    """Descobre o tipo pelo nome do arquivo."""
    nome = nome.upper()
    tipos = PRINCIPAIS + list(AUXILIARES.keys())
    for tipo in tipos:
        if tipo in nome:
            return tipo
    return None


def main():
    # 1. Receita: detecta competencia e lista arquivos
    receita = Receita()

    competencia = COMPETENCIA or receita.detectar_competencia()
    if not competencia:
        print("Erro: nao foi possivel detectar a competencia")
        return

    print("=" * 50)
    print("IMPORTACAO", competencia)
    print("=" * 50)

    # 2. Banco
    banco = Banco()
    if not banco.testar():
        return
    print("Banco conectado")

    banco.configurar_sessao()

    # 3. Lista arquivos
    links = receita.listar(competencia)
    if not links:
        print("Nenhum arquivo encontrado")
        return

    # 4. Estado dos hashes
    estado = Estado(competencia)
    hashes_antigos = estado.carregar()
    hashes_novos = {}
    arquivos_novos = []

    # 5. Verifica hashes (ETag tem prioridade)
    print("\nVerificando hashes...")
    for url in links:
        nome = os.path.basename(url)
        etag = receita.obter_etag(url)

        if etag:
            hashes_novos[nome] = etag

            if hashes_antigos.get(nome) == etag:
                print(f"  {nome}: sem alteracao")
                continue

            print(f"  {nome}: novo/alterado")
            arquivos_novos.append(url)
        else:
            print(f"  {nome}: sem ETag - vai baixar para verificar")
            arquivos_novos.append(url)

    if not arquivos_novos:
        print("\nNada novo para importar")
        return

    # 6. Limpa staging
    banco.limpar_staging()

    # 7. Importa
    importador = Importador(banco)
    processados = 0

    for url in arquivos_novos:
        nome = os.path.basename(url)
        tipo = identificar_tipo(nome)

        if not tipo:
            print("Ignorando:", nome)
            continue

        print("\nProcessando:", nome)

        zip_file = receita.baixar(url)
        if not zip_file:
            continue

        arquivo = receita.extrair(zip_file)
        if not arquivo:
            print("Erro na extracao")
            try:
                os.remove(zip_file)
            except:
                pass
            continue

        if importador.importar(arquivo, tipo):
            print(tipo, "OK")
            processados += 1

            # ETag tem prioridade; MD5 so como fallback
            if nome not in hashes_novos:
                hash_local = Estado.md5(zip_file)
                if hash_local:
                    hashes_novos[nome] = hash_local

            estado.salvar(hashes_novos)
        else:
            print(tipo, "FALHOU")

        try:
            os.remove(zip_file)
        except:
            pass

    if processados == 0:
        print("\nNenhum arquivo processado")
        return

    # 8. Consolida
    importador.consolidar()
    banco.restaurar_sessao()

    print("\n" + "=" * 50)
    print("FIM")
    print("Arquivos processados:", processados)
    print("=" * 50)


if __name__ == "__main__":
    main()
