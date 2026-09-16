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

load_dotenv()

# Configuracoes
PASTA_DOWNLOADS = "./downloads"
PASTA_STATE = "./state"
ANO_MES = os.getenv("COMPETENCIA", "2026-08")

DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME", "cnpj_db")

TOKEN = os.getenv("TOKEN_RECEITA", "YggdBLfdninEJX9")
TIMEOUT = 600

os.makedirs(PASTA_DOWNLOADS, exist_ok=True)
os.makedirs(PASTA_STATE, exist_ok=True)

engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?local_infile=1",
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600
)


# Hash e estado
def calcular_md5(caminho):
    try:
        with open(caminho, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        print(f"Erro MD5: {e}")
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


def obter_etag(url):
    try:
        r = requests.head(url, auth=(TOKEN, ""), timeout=30)
        if r.status_code == 200:
            return r.headers.get('ETag', '').strip('"') or None
    except Exception as e:
        print(f"Erro ETag: {e}")
    return None


# Listagem e download
def listar_arquivos():
    url = f"https://arquivos.receitafederal.gov.br/public.php/webdav/{ANO_MES}"
    print(f"Listando: {url}")
    try:
        r = requests.request(
            "PROPFIND", url,
            auth=(TOKEN, ""),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            timeout=30
        )
        if r.status_code in [200, 207]:
            root = ET.fromstring(r.content)
            ns = {'d': 'DAV:'}
            links = []
            for href in root.findall('.//d:href', ns):
                c = href.text
                if c and c.lower().endswith('.zip'):
                    if c.startswith('/'):
                        links.append(f"https://arquivos.receitafederal.gov.br{c}")
                    else:
                        links.append(c)
            print(f"WebDAV: {len(links)} arquivos")
            return links
    except Exception as e:
        print(f"WebDAV falhou: {e}")

    # Fallback Nextcloud
    print("Tentando Nextcloud...")
    url_nc = f"https://arquivos.receitafederal.gov.br/index.php/s/{TOKEN}?dir=/{ANO_MES}"
    try:
        r = requests.get(url_nc, timeout=30)
        r.raise_for_status()
        matches = re.findall(r'href="([^"]*\.zip[^"]*)"', r.text)
        links = []
        for m in matches:
            links.append(f"https://arquivos.receitafederal.gov.br{m}" if m.startswith('/') else m)
        print(f"Nextcloud: {len(links)} arquivos")
        return links
    except Exception as e:
        print(f"Nextcloud falhou: {e}")
        return []


def baixar_zip(url, destino):
    nome = os.path.basename(url)
    caminho = os.path.join(destino, nome)

    if os.path.exists(caminho) and zipfile.is_zipfile(caminho):
        return caminho, calcular_md5(caminho)

    print(f"Baixando {nome}...")
    try:
        with requests.get(url, auth=(TOKEN, ""), stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()
            with open(caminho, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        if not zipfile.is_zipfile(caminho):
            print(f"  {nome} nao e ZIP valido, descartando.")
            os.remove(caminho)
            url_nc = f"https://arquivos.receitafederal.gov.br/index.php/s/{TOKEN}/download?path=/{ANO_MES}/{nome}"
            with requests.get(url_nc, stream=True, timeout=TIMEOUT) as r:
                r.raise_for_status()
                with open(caminho, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            if not zipfile.is_zipfile(caminho):
                os.remove(caminho)
                return None, None

        h = calcular_md5(caminho)
        print(f"  OK ({h[:8]}...)")
        return caminho, h
    except Exception as e:
        print(f"  Erro: {e}")
        return None, None


# Extracao e carga
def extrair_zip(caminho_zip):
    try:
        base = os.path.dirname(caminho_zip)
        nome = os.path.splitext(os.path.basename(caminho_zip))[0]
        destino = os.path.join(base, nome)

        with zipfile.ZipFile(caminho_zip, 'r') as zf:
            zf.extractall(destino)

        for raiz, _, arquivos in os.walk(destino):
            for arq in arquivos:
                p = os.path.join(raiz, arq)
                if os.path.getsize(p) > 0:
                    return p
        return None
    except Exception as e:
        print(f"Erro extracao: {e}")
        return None


def executar_query(sql):
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
        return True
    except Exception as e:
        print(f"Erro query: {e}")
        return False


def processar_principal(caminho, tipo):
    if not caminho or not os.path.exists(caminho):
        return False

    c = caminho.replace('\\', '/')

    if tipo == "EMPRESA":
        sql = f"""
        LOAD DATA LOCAL INFILE '{c}'
        INTO TABLE empresas_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        (cnpj_basico, razao_social, natureza_juridica, qualificacao_responsavel, @cap_social, porte_empresa, ente_federativo_responsavel)
        SET capital_social = NULLIF(REPLACE(@cap_social, ',', '.'), '');
        """
    elif tipo == "ESTABELE":
        sql = f"""
        LOAD DATA LOCAL INFILE '{c}'
        INTO TABLE estabelecimentos_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
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
        LOAD DATA LOCAL INFILE '{c}'
        INTO TABLE socios_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        (cnpj_basico, identificador_socio, nome_socio_razao_social, cpf_cnpj_socio, qualificacao_socio, @data_ent, pais, representante_legal, nome_do_representante, qualificacao_representante_legal, faixa_etaria)
        SET data_entrada_sociedade = IF(@data_ent REGEXP '^[0-9]{{8}}$' AND @data_ent != '00000000', STR_TO_DATE(@data_ent, '%%Y%%m%%d'), NULL);
        """
    elif tipo == "SIMPLES":
        sql = f"""
        LOAD DATA LOCAL INFILE '{c}'
        INTO TABLE simples_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
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


# Importacao auxiliares
def importar_cnaes(caminho):
    executar_query("TRUNCATE TABLE cnaes;")
    c = caminho.replace('\\', '/')
    sql = f"""
    LOAD DATA LOCAL INFILE '{c}'
    INTO TABLE cnaes
    CHARACTER SET latin1
    FIELDS TERMINATED BY ';' ENCLOSED BY '"'
    LINES TERMINATED BY '\\n'
    IGNORE 1 LINES
    (codigo, descricao);
    """
    return executar_query(sql)


def importar_municipios(caminho):
    executar_query("TRUNCATE TABLE municipios;")
    c = caminho.replace('\\', '/')
    sql = f"""
    LOAD DATA LOCAL INFILE '{c}'
    INTO TABLE municipios
    CHARACTER SET latin1
    FIELDS TERMINATED BY ';' ENCLOSED BY '"'
    LINES TERMINATED BY '\\n'
    IGNORE 1 LINES
    (codigo, nome, uf);
    """
    return executar_query(sql)


def importar_naturezas(caminho):
    executar_query("TRUNCATE TABLE naturezas;")
    c = caminho.replace('\\', '/')
    sql = f"""
    LOAD DATA LOCAL INFILE '{c}'
    INTO TABLE naturezas
    CHARACTER SET latin1
    FIELDS TERMINATED BY ';' ENCLOSED BY '"'
    LINES TERMINATED BY '\\n'
    IGNORE 1 LINES
    (codigo, descricao);
    """
    return executar_query(sql)


def importar_paises(caminho):
    executar_query("TRUNCATE TABLE paises;")
    c = caminho.replace('\\', '/')
    sql = f"""
    LOAD DATA LOCAL INFILE '{c}'
    INTO TABLE paises
    CHARACTER SET latin1
    FIELDS TERMINATED BY ';' ENCLOSED BY '"'
    LINES TERMINATED BY '\\n'
    IGNORE 1 LINES
    (codigo, descricao);
    """
    return executar_query(sql)


def importar_motivos(caminho):
    executar_query("TRUNCATE TABLE motivos;")
    c = caminho.replace('\\', '/')
    sql = f"""
    LOAD DATA LOCAL INFILE '{c}'
    INTO TABLE motivos
    CHARACTER SET latin1
    FIELDS TERMINATED BY ';' ENCLOSED BY '"'
    LINES TERMINATED BY '\\n'
    IGNORE 1 LINES
    (codigo, descricao);
    """
    return executar_query(sql)


def importar_qualificacoes(caminho):
    executar_query("TRUNCATE TABLE qualificacoes;")
    c = caminho.replace('\\', '/')
    sql = f"""
    LOAD DATA LOCAL INFILE '{c}'
    INTO TABLE qualificacoes
    CHARACTER SET latin1
    FIELDS TERMINATED BY ';' ENCLOSED BY '"'
    LINES TERMINATED BY '\\n'
    IGNORE 1 LINES
    (codigo, descricao);
    """
    return executar_query(sql)


# Mapeamento de arquivos
IMPORTADORES = {
    "EMPRESA": lambda c: processar_principal(c, "EMPRESA"),
    "ESTABELE": lambda c: processar_principal(c, "ESTABELE"),
    "SOCIO": lambda c: processar_principal(c, "SOCIO"),
    "SIMPLES": lambda c: processar_principal(c, "SIMPLES"),
    "CNAES": importar_cnaes,
    "MUNICIPIOS": importar_municipios,
    "NATUREZAS": importar_naturezas,
    "PAISES": importar_paises,
    "MOTIVOS": importar_motivos,
    "QUALIFICACOES": importar_qualificacoes,
}


# Consolidacao
def consolidar_dados():
    print("\nConsolidando...")

    tabelas = [
        ("empresas", "razao_social, natureza_juridica, qualificacao_responsavel, capital_social, porte_empresa, ente_federativo_responsavel"),
        ("estabelecimentos", "identificador_matriz_filial, nome_fantasia, situacao_cadastral, data_situacao_cadastral, motivo_situacao_cadastral, nome_cidade_exterior, pais, data_inicio_atividade, cnae_fiscal_principal, cnae_fiscal_secundaria, tipo_logradouro, logradouro, numero, complemento, bairro, cep, uf, municipio, ddd1, telefone1, ddd2, telefone2, ddd_fax, fax, correio_eletronico, situacao_especial, data_situacao_especial"),
        ("socios", "identificador_socio, nome_socio_razao_social, data_entrada_sociedade, pais, representante_legal, nome_do_representante, qualificacao_representante_legal, faixa_etaria"),
        ("simples", "opcao_simples, data_opcao_simples, data_exclusao_simples, opcao_mei, data_opcao_mei, data_exclusao_mei")
    ]

    for nome, cols in tabelas:
        print(f"  {nome}...")
        updates = ", ".join([f"{c.strip()} = VALUES({c.strip()})" for c in cols.split(",")])
        sql = f"""
        INSERT INTO {nome}
        SELECT DISTINCT stg.* FROM {nome}_staging stg
        ON DUPLICATE KEY UPDATE {updates}
        """
        executar_query(sql)

    print("\nLimpando staging...")
    for t in ['empresas_staging', 'estabelecimentos_staging', 'socios_staging', 'simples_staging']:
        executar_query(f"TRUNCATE TABLE {t};")


# Main
def main():
    print("=" * 60)
    print(f"IMPORTACAO {ANO_MES}")
    print("=" * 60)

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Banco conectado")
    except Exception as e:
        print(f"Erro banco: {e}")
        return

    executar_query("SET SESSION sql_mode = '';")
    executar_query("SET SESSION unique_checks = 0;")
    executar_query("SET SESSION foreign_key_checks = 0;")

    print("\nListando arquivos...")
    links = listar_arquivos()
    if not links:
        print("Nada encontrado")
        return

    hashes_antigos = carregar_hashes()
    hashes_novos = {}
    baixar = []

    print("\nVerificando hashes...")
    for url in links:
        nome = os.path.basename(url)
        etag = obter_etag(url)
        if etag:
            hashes_novos[nome] = etag
            if nome in hashes_antigos and hashes_antigos[nome] == etag:
                print(f"  {nome}: sem mudanca")
                continue
            print(f"  {nome}: atualizado")
        else:
            print(f"  {nome}: sem ETag")
        baixar.append(url)

    # Nao salva os hashes aqui. Apenas apos processar com sucesso.

    if not baixar:
        print("\nNada novo")
        return

    print("\nLimpando staging...")
    for t in ['empresas_staging', 'estabelecimentos_staging', 'socios_staging', 'simples_staging']:
        executar_query(f"TRUNCATE TABLE {t};")

    processados = 0
    for url in baixar:
        nome = os.path.basename(url)
        nome_up = nome.upper()

        tipo = None
        for chave in IMPORTADORES:
            if chave in nome_up:
                tipo = chave
                break

        if not tipo:
            print(f"Ignorando: {nome}")
            continue

        print(f"\nProcessando {tipo}...")
        caminho_zip, hash_local = baixar_zip(url, PASTA_DOWNLOADS)
        if not caminho_zip:
            continue

        arquivo = extrair_zip(caminho_zip)
        if not arquivo:
            print(f"  Falha extracao")
            try:
                os.remove(caminho_zip)
            except:
                pass
            continue

        if IMPORTADORES[tipo](arquivo):
            processados += 1
            print(f"  {tipo} OK")

            # Salva o hash apenas apos sucesso
            if hash_local:
                hashes_novos[nome] = hash_local
            if nome not in hashes_novos and nome in hashes_antigos:
                # mantem o ETag antigo se nao tiver hash local
                hashes_novos[nome] = hashes_antigos[nome]
            salvar_hashes(hashes_novos)
        else:
            print(f"  {tipo} falhou")

        try:
            os.remove(caminho_zip)
        except:
            pass

    if processados == 0:
        print("\nNada processado")
        return

    consolidar_dados()

    executar_query("SET foreign_key_checks = 1;")
    executar_query("SET unique_checks = 1;")

    print("\n" + "=" * 60)
    print(f"FIM. {processados} arquivos processados.")
    print("=" * 60)


if __name__ == "__main__":
    main()