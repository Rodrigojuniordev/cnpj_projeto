# -*- coding: utf-8 -*-
import os
import zipfile
import requests
import xml.etree.ElementTree as ET
from sqlalchemy import create_engine, text
import hashlib
import json
import re
from dotenv import load_dotenv
import time

load_dotenv()

# ============================================================
# CONFIGURAÇÕES
# ============================================================
PASTA_DOWNLOADS = "./downloads"
PASTA_STATE = "./state"
ANO_MES = os.getenv("COMPETENCIA", "2026-08")

DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "u62iqi4i")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME", "cnpj_db")

os.makedirs(PASTA_DOWNLOADS, exist_ok=True)
os.makedirs(PASTA_STATE, exist_ok=True)

engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?local_infile=1",
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600
)

# ============================================================
# FUNÇÕES DE HASH E CONTROLE DE ESTADO
# ============================================================

def calcular_md5(caminho):
    try:
        with open(caminho, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        print(f"Erro no MD5: {e}")
        return None

def carregar_hashes():
    arquivo = os.path.join(PASTA_STATE, f"hashes_{ANO_MES}.json")
    if os.path.exists(arquivo):
        try:
            with open(arquivo, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def salvar_hashes(hashes):
    arquivo = os.path.join(PASTA_STATE, f"hashes_{ANO_MES}.json")
    with open(arquivo, 'w') as f:
        json.dump(hashes, f, indent=4, ensure_ascii=False)
    print(f"Hashers salvos em {arquivo}")

def obter_etag_remoto(url):
    """Tenta obter o ETag sem baixar o arquivo inteiro."""
    try:
        resp = requests.head(url, auth=("YggdBLfdninEJX9", ""), timeout=30)
        if resp.status_code == 200:
            etag = resp.headers.get('ETag', '').strip('"')
            if etag:
                return etag
        return None
    except Exception as e:
        print(f"Falha ao obter ETag: {e}")
        return None

# ============================================================
# FUNÇÕES DE LISTAGEM E DOWNLOAD (COM FALLBACK)
# ============================================================

def listar_arquivos_webdav():
    """Tenta listar pelo WebDAV. Se falhar, usa o Nextcloud."""
    url = f"https://arquivos.receitafederal.gov.br/public.php/webdav/{ANO_MES}"
    print(f"Listando via WebDAV: {url}")
    try:
        resp = requests.request(
            "PROPFIND",
            url,
            auth=("YggdBLfdninEJX9", ""),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            timeout=30
        )
        if resp.status_code in [200, 207]:
            root = ET.fromstring(resp.content)
            ns = {'d': 'DAV:'}
            links = []
            for href in root.findall('.//d:href', ns):
                caminho = href.text
                if caminho and caminho.lower().endswith('.zip'):
                    if caminho.startswith('/'):
                        links.append(f"https://arquivos.receitafederal.gov.br{caminho}")
                    else:
                        links.append(caminho)
            print(f"WebDAV encontrou {len(links)} arquivos.")
            return links
    except Exception as e:
        print(f"WebDAV falhou: {e}")

    # Fallback: parse da página do Nextcloud
    print("Tentando obter lista via Nextcloud...")
    url_nc = f"https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9?dir=/{ANO_MES}"
    try:
        resp = requests.get(url_nc, timeout=30)
        resp.raise_for_status()
        padrao = r'href="([^"]*\.zip[^"]*)"'
        matches = re.findall(padrao, resp.text)
        links = []
        for match in matches:
            if match.startswith('/'):
                links.append(f"https://arquivos.receitafederal.gov.br{match}")
            else:
                links.append(match)
        print(f"Nextcloud encontrou {len(links)} arquivos.")
        return links
    except Exception as e:
        print(f"Nextcloud também falhou: {e}")
        return []

def baixar_zip(url, destino):
    """Baixa o arquivo e verifica se é realmente um ZIP."""
    nome = os.path.basename(url)
    caminho = os.path.join(destino, nome)

    # Se já existe e é válido, reutiliza
    if os.path.exists(caminho) and zipfile.is_zipfile(caminho):
        hash_local = calcular_md5(caminho)
        print(f"Arquivo {nome} já existe e é um ZIP válido.")
        return caminho, hash_local

    print(f"Baixando {nome}...")
    try:
        # Tenta baixar com autenticação WebDAV
        with requests.get(url, auth=("YggdBLfdninEJX9", ""), stream=True, timeout=120) as r:
            r.raise_for_status()
            # Verifica o Content-Type
            if 'zip' not in r.headers.get('Content-Type', '').lower():
                print(f"  Aviso: Content-Type não é ZIP ({r.headers.get('Content-Type')})")
            with open(caminho, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)

        # Verifica se o arquivo é um ZIP válido
        if not zipfile.is_zipfile(caminho):
            print(f"  Erro: {nome} não é um ZIP válido. Descartando.")
            os.remove(caminho)
            # Tenta a URL do Nextcloud como fallback
            url_nc = f"https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9/download?path=/{ANO_MES}/{nome}"
            print(f"  Tentando download via Nextcloud: {url_nc}")
            with requests.get(url_nc, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(caminho, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
            if not zipfile.is_zipfile(caminho):
                print(f"  Falha também pelo Nextcloud. Descartando {nome}.")
                os.remove(caminho)
                return None, None

        hash_local = calcular_md5(caminho)
        print(f"  Download concluído (MD5: {hash_local[:8]}...)")
        return caminho, hash_local

    except Exception as e:
        print(f"Erro no download de {nome}: {e}")
        return None, None

# ============================================================
# FUNÇÕES DE EXTRAÇÃO E CARGA
# ============================================================

def extrair_zip(caminho_zip):
    try:
        pasta_base = os.path.dirname(caminho_zip)
        nome_sem_zip = os.path.splitext(os.path.basename(caminho_zip))[0]
        pasta_extraida = os.path.join(pasta_base, nome_sem_zip)

        with zipfile.ZipFile(caminho_zip, 'r') as zf:
            zf.extractall(pasta_extraida)

        for raiz, _, arquivos in os.walk(pasta_extraida):
            for arq in arquivos:
                caminho = os.path.join(raiz, arq)
                if os.path.getsize(caminho) > 0:
                    return caminho
        return None
    except Exception as e:
        print(f"Erro ao extrair {caminho_zip}: {e}")
        return None

def executar_query(sql):
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
        return True
    except Exception as e:
        print(f"Erro na query: {e}")
        return False

def processar_arquivo(caminho_arquivo, tipo):
    if not caminho_arquivo or not os.path.exists(caminho_arquivo):
        return False

    caminho_sql = caminho_arquivo.replace('\\', '/')

    # Detecta cabeçalho
    try:
        with open(caminho_arquivo, 'r', encoding='latin1') as f:
            primeira = f.readline()
            ignora_cabecalho = "IGNORE 1 LINES" if ('CNPJ' in primeira.upper() or 'SOCIO' in primeira.upper()) else ""
    except:
        ignora_cabecalho = ""

    if tipo == "EMPRESA":
        sql = f"""
        LOAD DATA LOCAL INFILE '{caminho_sql}'
        INTO TABLE empresas_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        {ignora_cabecalho}
        (cnpj_basico, razao_social, natureza_juridica, qualificacao_responsavel, @cap_social, porte_empresa, ente_federativo_responsavel)
        SET capital_social = NULLIF(REPLACE(@cap_social, ',', '.'), '');
        """
    elif tipo == "ESTABELE":
        sql = f"""
        LOAD DATA LOCAL INFILE '{caminho_sql}'
        INTO TABLE estabelecimentos_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        {ignora_cabecalho}
        (cnpj_basico, cnpj_ordem, cnpj_dv, identificador_matriz_filial, nome_fantasia,
         situacao_cadastral, @data_sit, motivo_situacao_cadastral, nome_cidade_exterior,
         pais, @data_ini, cnae_fiscal_principal, cnae_fiscal_secundaria, tipo_logradouro,
         logradouro, numero, complemento, bairro, cep, uf, municipio, ddd1, telefone1,
         ddd2, telefone2, ddd_fax, fax, correio_eletronico, situacao_especial, @data_esp)
        SET
         data_situacao_cadastral = IF(@data_sit REGEXP '^[0-9]{{8}}$' AND @data_sit != '00000000', STR_TO_DATE(@data_sit, '%%Y%%m%%d'), NULL),
         data_inicio_atividade   = IF(@data_ini REGEXP '^[0-9]{{8}}$' AND @data_ini != '00000000', STR_TO_DATE(@data_ini, '%%Y%%m%%d'), NULL),
         data_situacao_especial  = IF(@data_esp REGEXP '^[0-9]{{8}}$' AND @data_esp != '00000000', STR_TO_DATE(@data_esp, '%%Y%%m%%d'), NULL);
        """
    elif tipo == "SOCIO":
        sql = f"""
        LOAD DATA LOCAL INFILE '{caminho_sql}'
        INTO TABLE socios_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        {ignora_cabecalho}
        (cnpj_basico, identificador_socio, nome_socio_razao_social, cpf_cnpj_socio, qualificacao_socio, @data_ent, pais, representante_legal, nome_do_representante, qualificacao_representante_legal, faixa_etaria)
        SET data_entrada_sociedade = IF(@data_ent REGEXP '^[0-9]{{8}}$' AND @data_ent != '00000000', STR_TO_DATE(@data_ent, '%%Y%%m%%d'), NULL);
        """
    elif tipo == "SIMPLES":
        sql = f"""
        LOAD DATA LOCAL INFILE '{caminho_sql}'
        INTO TABLE simples_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        {ignora_cabecalho}
        (cnpj_basico, opcao_simples, @data_op_simples, @data_ex_simples, opcao_mei, @data_op_mei, @data_ex_mei)
        SET
         data_opcao_simples    = IF(@data_op_simples REGEXP '^[0-9]{{8}}$' AND @data_op_simples != '00000000', STR_TO_DATE(@data_op_simples, '%%Y%%m%%d'), NULL),
         data_exclusao_simples = IF(@data_ex_simples REGEXP '^[0-9]{{8}}$' AND @data_ex_simples != '00000000', STR_TO_DATE(@data_ex_simples, '%%Y%%m%%d'), NULL),
         data_opcao_mei        = IF(@data_op_mei REGEXP '^[0-9]{{8}}$' AND @data_op_mei != '00000000', STR_TO_DATE(@data_op_mei, '%%Y%%m%%d'), NULL),
         data_exclusao_mei     = IF(@data_ex_mei REGEXP '^[0-9]{{8}}$' AND @data_ex_mei != '00000000', STR_TO_DATE(@data_ex_mei, '%%Y%%m%%d'), NULL);
        """
    else:
        return False

    return executar_query(sql)

# ============================================================
# CONSOLIDAÇÃO INCREMENTAL (ON DUPLICATE KEY UPDATE)
# ============================================================

def consolidar_dados():
    print("\nConsolidando dados...")

    for tabela in [
        ("empresas", "razao_social, natureza_juridica, qualificacao_responsavel, capital_social, porte_empresa, ente_federativo_responsavel"),
        ("estabelecimentos", """identificador_matriz_filial, nome_fantasia, situacao_cadastral, data_situacao_cadastral, motivo_situacao_cadastral, nome_cidade_exterior, pais, data_inicio_atividade, cnae_fiscal_principal, cnae_fiscal_secundaria, tipo_logradouro, logradouro, numero, complemento, bairro, cep, uf, municipio, ddd1, telefone1, ddd2, telefone2, ddd_fax, fax, correio_eletronico, situacao_especial, data_situacao_especial"""),
        ("socios", """identificador_socio, nome_socio_razao_social, data_entrada_sociedade, pais, representante_legal, nome_do_representante, qualificacao_representante_legal, faixa_etaria"""),
        ("simples", """opcao_simples, data_opcao_simples, data_exclusao_simples, opcao_mei, data_opcao_mei, data_exclusao_mei""")
    ]:
        nome, colunas = tabela
        print(f"  Consolidando {nome}...")
        sql = f"""
        INSERT INTO {nome}
        SELECT DISTINCT stg.* FROM {nome}_staging stg
        ON DUPLICATE KEY UPDATE {', '.join([c + ' = VALUES(' + c + ')' for c in colunas.split(', ')])}
        """
        executar_query(sql)

    # Limpeza das staging
    print("\nLimpando staging...")
    for t in ['empresas_staging', 'estabelecimentos_staging', 'socios_staging', 'simples_staging']:
        executar_query(f"TRUNCATE TABLE {t};")
    print("Staging limpas.")

# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print(f"IMPORTACAO INCREMENTAL {ANO_MES} - COM VERIFICACAO DE HASH")
    print("=" * 60)

    # Conexão com o banco
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Banco conectado.")
    except Exception as e:
        print(f"Erro no banco: {e}")
        return

    # Ajustes de sessão
    executar_query("SET SESSION sql_mode = '';")
    executar_query("SET SESSION unique_checks = 0;")
    executar_query("SET SESSION foreign_key_checks = 0;")

    # Lista arquivos
    print("\nListando arquivos...")
    links = listar_arquivos_webdav()
    if not links:
        print("Nenhum arquivo encontrado. Encerrando.")
        return

    # Carrega hashes antigos
    hashes_antigos = carregar_hashes()
    hashes_novos = {}
    arquivos_para_baixar = []

    print("\nVerificando hashes remotos (ETag)...")
    for url in links:
        nome = os.path.basename(url)
        etag = obter_etag_remoto(url)
        if etag:
            hashes_novos[nome] = etag
            if nome in hashes_antigos and hashes_antigos[nome] == etag:
                print(f"  {nome}: hash igual ao mês passado - ignorando (sem download)")
                continue
            else:
                print(f"  {nome}: hash diferente ou novo - será baixado")
                arquivos_para_baixar.append(url)
        else:
            print(f"  {nome}: não foi possível obter ETag - será baixado para verificação")
            arquivos_para_baixar.append(url)

    # Salva os hashes atuais (os que conseguimos obter)
    salvar_hashes(hashes_novos)

    if not arquivos_para_baixar:
        print("\nNenhum arquivo novo ou modificado. Finalizando.")
        return

    # Limpa staging antes de processar
    print("\nLimpando staging...")
    for t in ['empresas_staging', 'estabelecimentos_staging', 'socios_staging', 'simples_staging']:
        executar_query(f"TRUNCATE TABLE {t};")

    processados = 0
    for url in arquivos_para_baixar:
        nome = os.path.basename(url).upper()
        tipo = None
        if "EMPRESA" in nome:
            tipo = "EMPRESA"
        elif "ESTABELE" in nome:
            tipo = "ESTABELE"
        elif "SOCIO" in nome:
            tipo = "SOCIO"
        elif "SIMPLES" in nome:
            tipo = "SIMPLES"
        else:
            print(f"Ignorando arquivo auxiliar: {os.path.basename(url)}")
            continue

        print(f"\nProcessando {tipo}...")
        caminho_zip, hash_local = baixar_zip(url, PASTA_DOWNLOADS)
        if not caminho_zip:
            print(f"  Falha no download de {os.path.basename(url)}. Pulando.")
            continue

        # Se o ETag não estava disponível, atualiza o hash local
        if os.path.basename(url) not in hashes_novos:
            hashes_novos[os.path.basename(url)] = hash_local
            salvar_hashes(hashes_novos)

        arquivo_dados = extrair_zip(caminho_zip)
        if not arquivo_dados:
            print(f"  Falha na extração de {caminho_zip}. Pulando.")
            continue

        if processar_arquivo(arquivo_dados, tipo):
            processados += 1

        # Remove o ZIP após processar
        try:
            os.remove(caminho_zip)
            print(f"  {os.path.basename(caminho_zip)} removido.")
        except Exception as e:
            print(f"  Não foi possível remover {os.path.basename(caminho_zip)}: {e}")

    if processados == 0:
        print("\nNenhum arquivo foi processado com sucesso.")
        return

    consolidar_dados()
    executar_query("SET foreign_key_checks = 1;")
    executar_query("SET unique_checks = 1;")

    print("\n" + "=" * 60)
    print(f"IMPORTACAO CONCLUIDA. {processados} arquivo(s) processado(s).")
    print("=" * 60)

if __name__ == "__main__":
    main()
