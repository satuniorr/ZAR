# -*- coding: utf-8 -*-
import os
import sqlite3
import pandas as pd
import hashlib
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.utils import secure_filename
import numpy as np
import logging

# --- Configuração de Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuração Inicial ---
# Usar caminhos relativos para templates e static
app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.urandom(24)

# Define BASE_DIR relativo à localização de main.py
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SRC_DIR)

DATABASE = os.path.join(BASE_DIR, 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'xlsx'}
ADMIN_PASSWORD_HASH = hashlib.sha256('#compras321!'.encode()).hexdigest()

if not os.path.exists(UPLOAD_FOLDER):
    try:
        os.makedirs(UPLOAD_FOLDER)
        logger.info(f"Diretório de uploads criado em {UPLOAD_FOLDER}")
    except OSError as e:
        logger.error(f"Erro ao criar diretório de uploads {UPLOAD_FOLDER}: {e}")

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Mapeamento de Colunas (Excel do Usuário -> Interno) ---
COLUMN_MAPPING = {
    'Solicitação': 'Solicitacao',
    'DtAprovSol': 'DtAprovSol',
    'Comprador': 'Comprador',
    'Fornec': 'Fornecedor',
    'Descrição': 'Produto',
    'Qt.Solicitada': 'Qtde',
    'Pre‡o Unit	ário': 'PrecoUnitario',
    'Preço Unitário': 'PrecoUnitario',
    'Vlr Total': 'VlrTotal',
    'DtAprovPedido': 'DtAprovPedido',
    'Dt.Pedido': 'DtPedido',
    'Pedido': 'Pedido',
    'Dt.EntregaOrig': 'DtEntregaOrig',
    'Dt.Receb': 'DtReceb',
    'Estado': 'Status',
    'Etapa': 'Etapa',
    'Dias Atr Sol': 'DiasAtrSol',
}

INTERNAL_COLUMNS = [
    'Solicitacao', 'DtAbertura', 'DtAprovSol', 'Comprador', 'Fornecedor',
    'Produto', 'Qtde', 'PrecoUnitario', 'PrecoUnitarioOrig', 'Moeda', 'VlrTotal',
    'DtAprovPedido', 'DtPedido', 'Pedido', 'DtEntregaOrig', 'DtEntregaAtual',
    'DtReceb', 'Status', 'Etapa', 'DiasAtrSol',
    'LeadTimeCompra', 'LeadTimeEntrega', 'AtrasoEntrega'
]

# --- Funções Auxiliares ---
def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_date(date_str):
    if isinstance(date_str, datetime):
        return date_str.strftime('%Y-%m-%d')
    if isinstance(date_str, str):
        try:
            dt_obj = pd.to_datetime(date_str, errors='coerce', dayfirst=True)
            if pd.notna(dt_obj):
                return dt_obj.strftime('%Y-%m-%d')
        except Exception as e:
            logger.warning(f"Erro ao parsear data '{date_str}': {e}")
            return None
    return None

def clean_price(price_str):
    if price_str is None:
        return None
    try:
        cleaned = str(price_str)
        cleaned = re.sub(r'[R$\s.]', '', cleaned)
        cleaned = cleaned.replace(',', '.')
        if not cleaned:
            return None
        return float(cleaned)
    except (ValueError, TypeError) as e:
        logger.warning(f"Erro ao limpar preço '{price_str}': {e}")
        return None

def calculate_lead_time_compra(dt_pedido_str, dt_aprov_sol_str):
    dt_pedido = pd.to_datetime(dt_pedido_str, errors='coerce')
    dt_aprov_sol = pd.to_datetime(dt_aprov_sol_str, errors='coerce')
    if pd.isna(dt_pedido) or pd.isna(dt_aprov_sol):
        return None
    if dt_pedido < dt_aprov_sol:
        return 'contrato'
    return (dt_pedido - dt_aprov_sol).days

def calculate_lead_time_entrega(dt_receb_str, dt_aprov_pedido_str):
    dt_receb = pd.to_datetime(dt_receb_str, errors='coerce')
    dt_aprov_pedido = pd.to_datetime(dt_aprov_pedido_str, errors='coerce')
    if pd.isna(dt_receb) or pd.isna(dt_aprov_pedido):
        return None
    if dt_receb >= dt_aprov_pedido:
        return (dt_receb - dt_aprov_pedido).days
    else:
        return None

def calculate_atraso_entrega(dt_receb_str, dt_entrega_orig_str):
    dt_receb = pd.to_datetime(dt_receb_str, errors='coerce')
    dt_entrega_orig = pd.to_datetime(dt_entrega_orig_str, errors='coerce')
    if pd.isna(dt_receb) or pd.isna(dt_entrega_orig):
        return None
    delta = (dt_receb - dt_entrega_orig).days
    return max(0, delta)

# --- Funções do Banco de Dados ---
def get_db():
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        # logger.info(f"Conectado ao banco de dados: {DATABASE}") # Log excessivo
        return conn
    except sqlite3.Error as e:
        logger.error(f"Erro ao conectar ao banco de dados {DATABASE}: {e}")
        return None

def init_db(force_create=False):
    conn = get_db()
    if not conn:
        logger.error("init_db: Falha ao obter conexão com o banco de dados.")
        return
    cursor = conn.cursor()
    try:
        if force_create:
            cursor.execute("DROP TABLE IF EXISTS solicitacoes")
            logger.info("Tabela 'solicitacoes' existente removida (force_create=True).")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='solicitacoes'")
        table_exists = cursor.fetchone()
        if not table_exists:
            logger.info("Criando tabela 'solicitacoes'...")
            cols_definition = []
            for col in INTERNAL_COLUMNS:
                if col == 'id': continue
                col_type = 'INTEGER' if col in ['DiasAtrSol', 'LeadTimeEntrega', 'AtrasoEntrega'] else \
                           'REAL' if col in ['Qtde', 'PrecoUnitario', 'VlrTotal'] else \
                           'TEXT'
                cols_definition.append(f'{col} {col_type}')

            create_table_sql = f"""
                CREATE TABLE solicitacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    {', '.join(cols_definition)}
                )
            """
            cursor.execute(create_table_sql)
            conn.commit()
            logger.info("Tabela 'solicitacoes' criada.")
        # else:
            # logger.info("Tabela 'solicitacoes' já existe.") # Log excessivo
    except sqlite3.Error as e:
        logger.error(f"Erro durante init_db: {e}")
    finally:
        if conn:
            conn.close()
            # logger.info("init_db: Conexão com o banco de dados fechada.") # Log excessivo

def process_and_load_excel(file_path):
    conn = None
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
        original_columns = df.columns.tolist()
        logger.info(f"Colunas originais encontradas no Excel: {original_columns}")

        reverse_mapping = {v: k for k, v in COLUMN_MAPPING.items()}
        essential_internal_cols = [
            'Solicitacao', 'DtAprovSol', 'Comprador', 'Fornecedor', 'Produto',
            'Qtde', 'PrecoUnitario', 'VlrTotal', 'DtAprovPedido', 'DtPedido',
            'Pedido', 'DtEntregaOrig', 'DtReceb', 'Status', 'Etapa', 'DiasAtrSol'
        ]
        missing_original_cols = []
        present_original_cols = {}
        for internal_col in essential_internal_cols:
            original_col_name = reverse_mapping.get(internal_col)
            if original_col_name and original_col_name in original_columns:
                present_original_cols[internal_col] = original_col_name
            else:
                # Tentativa flexível de encontrar colunas comuns
                found_flexible = False
                if internal_col == 'PrecoUnitario':
                    if 'Preço Unitário' in original_columns:
                        present_original_cols[internal_col] = 'Preço Unitário'
                        found_flexible = True
                    elif 'Pre‡o Unit	ário' in original_columns:
                        present_original_cols[internal_col] = 'Pre‡o Unit	ário'
                        found_flexible = True
                elif internal_col == 'VlrTotal' and 'Vlr Total' in original_columns:
                    present_original_cols[internal_col] = 'Vlr Total'
                    found_flexible = True
                elif internal_col == 'DiasAtrSol' and 'Dias Atr Sol' in original_columns:
                    present_original_cols[internal_col] = 'Dias Atr Sol'
                    found_flexible = True
                elif internal_col == 'Produto' and 'Descrição' in original_columns:
                    present_original_cols[internal_col] = 'Descrição'
                    found_flexible = True
                elif internal_col == 'Qtde' and 'Qt.Solicitada' in original_columns:
                    present_original_cols[internal_col] = 'Qt.Solicitada'
                    found_flexible = True
                elif internal_col == 'Status' and 'Estado' in original_columns:
                    present_original_cols[internal_col] = 'Estado'
                    found_flexible = True
                elif internal_col == 'Fornecedor' and 'Fornec' in original_columns:
                    present_original_cols[internal_col] = 'Fornec'
                    found_flexible = True
                elif internal_col == 'DtPedido' and 'Dt.Pedido' in original_columns:
                    present_original_cols[internal_col] = 'Dt.Pedido'
                    found_flexible = True
                elif internal_col == 'DtEntregaOrig' and 'Dt.EntregaOrig' in original_columns:
                    present_original_cols[internal_col] = 'Dt.EntregaOrig'
                    found_flexible = True
                elif internal_col == 'DtReceb' and 'Dt.Receb' in original_columns:
                    present_original_cols[internal_col] = 'Dt.Receb'
                    found_flexible = True

                if not found_flexible:
                    missing_original_cols.append(internal_col)

        if missing_original_cols:
            logger.error(f"Erro: Colunas essenciais não encontradas ou mapeadas no arquivo Excel: {missing_original_cols}")
            return False, f"Colunas essenciais não encontradas/mapeadas: {', '.join(missing_original_cols)}"
        logger.info(f"Colunas essenciais mapeadas com sucesso: {present_original_cols}")

        conn = get_db()
        if not conn:
             return False, "Falha ao conectar ao banco de dados."

        init_db() # Garante que a tabela exista

        cursor = conn.cursor()
        cursor.execute("DELETE FROM solicitacoes")
        logger.info("Dados antigos da tabela 'solicitacoes' removidos.")

        rows_processed = 0
        for index, row in df.iterrows():
            try:
                insert_data = {}
                for internal_col in INTERNAL_COLUMNS:
                    if internal_col == 'id': continue

                    original_col = present_original_cols.get(internal_col)
                    value = row.get(original_col) if original_col else None

                    # Tratamentos específicos
                    if internal_col in ['DtAbertura', 'DtAprovSol', 'DtAprovPedido', 'DtPedido', 'DtEntregaOrig', 'DtEntregaAtual', 'DtReceb']:
                        insert_data[internal_col] = parse_date(value)
                    elif internal_col == 'PrecoUnitario':
                        insert_data[internal_col] = clean_price(value)
                        insert_data['PrecoUnitarioOrig'] = str(value) if value is not None else None
                    elif internal_col == 'VlrTotal':
                        insert_data[internal_col] = clean_price(value)
                    elif internal_col == 'Comprador':
                        comprador_raw = str(value).strip().title() if value else ''
                        insert_data[internal_col] = comprador_raw if comprador_raw in ['Miriam', 'Irineu'] else 'Outro'
                    elif internal_col == 'Status':
                        status_raw = str(value).strip().lower() if value else ''
                        insert_data[internal_col] = 'não aprovado' if status_raw == 'nao aprovado' else status_raw
                    elif internal_col == 'DiasAtrSol':
                         dias_atr_sol_raw = value
                         insert_data[internal_col] = int(dias_atr_sol_raw) if pd.notna(dias_atr_sol_raw) and isinstance(dias_atr_sol_raw, (int, float)) else 0
                    elif internal_col == 'Moeda':
                        insert_data[internal_col] = None # Não presente no Excel do usuário
                    elif internal_col == 'DtAbertura':
                         insert_data[internal_col] = None # Não presente no Excel do usuário
                    elif internal_col == 'DtEntregaAtual':
                         insert_data[internal_col] = None # Não presente no Excel do usuário
                    else:
                        # Para colunas como Solicitacao, Fornecedor, Produto, Qtde, Pedido, Etapa
                        insert_data[internal_col] = value if pd.notna(value) else None

                # Calcular indicadores derivados
                insert_data['LeadTimeCompra'] = calculate_lead_time_compra(insert_data.get('DtPedido'), insert_data.get('DtAprovSol'))
                insert_data['LeadTimeEntrega'] = calculate_lead_time_entrega(insert_data.get('DtReceb'), insert_data.get('DtAprovPedido'))
                insert_data['AtrasoEntrega'] = calculate_atraso_entrega(insert_data.get('DtReceb'), insert_data.get('DtEntregaOrig'))

                # Garantir a ordem correta para inserção
                cols_for_insert = [col for col in INTERNAL_COLUMNS if col != 'id']
                placeholders = ', '.join(['?'] * len(cols_for_insert))
                sql = f"INSERT INTO solicitacoes ({', '.join(cols_for_insert)}) VALUES ({placeholders})"
                values_tuple = tuple(insert_data.get(col) for col in cols_for_insert)

                cursor.execute(sql, values_tuple)
                rows_processed += 1

            except Exception as row_error:
                 logger.error(f"Erro ao processar linha {index}: {row_error} - Dados da linha: {row.to_dict()}")
                 continue

        conn.commit()
        logger.info(f"Dados do arquivo {os.path.basename(file_path)} carregados com sucesso. {rows_processed} linhas processadas.")
        return True, f"{rows_processed} registros carregados com sucesso."

    except FileNotFoundError:
        logger.error(f"Erro: Arquivo não encontrado em {file_path}")
        return False, "Arquivo Excel não encontrado."
    except ImportError:
        logger.error("Erro: Biblioteca 'openpyxl' não encontrada. Necessária para ler arquivos .xlsx.")
        return False, "Dependência 'openpyxl' ausente."
    except Exception as e:
        logger.exception(f"Erro geral ao processar o arquivo Excel: {e}")
        if conn:
            try:
                conn.rollback()
            except sqlite3.Error as rb_err:
                 logger.error(f"Erro ao fazer rollback: {rb_err}")
        return False, f"Erro inesperado ao processar Excel: {e}"
    finally:
        if conn:
            conn.close()

# --- Funções para buscar dados do Dashboard ---
def get_dashboard_data():
    conn = get_db()
    if not conn:
        return {'error': 'Falha ao conectar ao banco de dados.'}
    cursor = conn.cursor()
    data = {}
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='solicitacoes'")
        if not cursor.fetchone():
            logger.warning("Tabela 'solicitacoes' não encontrada ao buscar dados do dashboard.")
            # Retorna um dicionário indicando que a tabela está vazia/não existe
            return {'tabela_vazia': True}

        cursor.execute("SELECT COUNT(*) FROM solicitacoes")
        total_solicitacoes = cursor.fetchone()[0]
        data['total_solicitacoes'] = total_solicitacoes

        # Se não houver solicitações, retornar dados vazios/padrão
        if total_solicitacoes == 0:
            logger.info("Tabela 'solicitacoes' está vazia.")
            data.update({
                'total_compras': 0,
                'por_comprador': {},
                'por_etapa': {},
                'atrasadas_cotacao': [],
                'lead_time_compra_medio': 'N/A',
                'lead_time_entrega_medio': 'N/A',
                'atraso_entrega_medio': 'N/A',
                'desempenho_comprador': {},
                'tabela_vazia': True # Indica que a tabela está vazia
            })
            return data
        else:
             data['tabela_vazia'] = False # Indica que há dados

        # Continuar buscando outros dados se a tabela não estiver vazia
        cursor.execute("SELECT SUM(VlrTotal) FROM solicitacoes WHERE Status = 'aprovado'")
        total_compras = cursor.fetchone()[0]
        data['total_compras'] = total_compras if total_compras else 0

        cursor.execute("SELECT Comprador, COUNT(*) as count FROM solicitacoes WHERE Comprador IN ('Miriam', 'Irineu') GROUP BY Comprador ORDER BY count DESC")
        data['por_comprador'] = {row['Comprador']: row['count'] for row in cursor.fetchall()}

        cursor.execute("SELECT Etapa, COUNT(*) as count FROM solicitacoes GROUP BY Etapa ORDER BY Etapa")
        data['por_etapa'] = {row['Etapa']: row['count'] for row in cursor.fetchall()}

        cursor.execute("SELECT Solicitacao, Etapa, Comprador, DiasAtrSol FROM solicitacoes WHERE Etapa IN ('02_COTAR', '05_COTADA') ORDER BY DiasAtrSol DESC")
        data['atrasadas_cotacao'] = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT LeadTimeCompra, LeadTimeEntrega, AtrasoEntrega FROM solicitacoes")
        all_indicators = cursor.fetchall()

        lt_compra_days = [int(i['LeadTimeCompra']) for i in all_indicators if i['LeadTimeCompra'] and i['LeadTimeCompra'].isdigit()]
        lt_entrega_days = [i['LeadTimeEntrega'] for i in all_indicators if i['LeadTimeEntrega'] is not None]
        atraso_entrega_days = [i['AtrasoEntrega'] for i in all_indicators if i['AtrasoEntrega'] is not None]

        data['lead_time_compra_medio'] = round(np.mean(lt_compra_days), 2) if lt_compra_days else 'N/A'
        data['lead_time_entrega_medio'] = round(np.mean(lt_entrega_days), 2) if lt_entrega_days else 'N/A'
        data['atraso_entrega_medio'] = round(np.mean(atraso_entrega_days), 2) if atraso_entrega_days else 'N/A'

        cursor.execute("SELECT Comprador, SUM(VlrTotal) as total FROM solicitacoes WHERE Status = 'aprovado' AND Comprador IN ('Miriam', 'Irineu') GROUP BY Comprador ORDER BY total DESC")
        data['desempenho_comprador'] = {row['Comprador']: row['total'] if row['total'] else 0 for row in cursor.fetchall()}

    except sqlite3.Error as e:
        logger.error(f"Erro ao buscar dados do dashboard: {e}")
        return {'error': f'Erro ao buscar dados: {e}'}
    finally:
        if conn:
            conn.close()
    return data

# --- Rota Principal (Chatbot) ---
@app.route('/')
def index():
    return render_template('index.html')

# --- Rotas da Área Administrativa ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('admin_dashboard'))
    error = None
    if request.method == 'POST':
        password = request.form['password']
        if hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
            session['logged_in'] = True
            flash('Login bem-sucedido!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            error = 'Senha incorreta!'
            flash(error, 'danger')
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('Você foi desconectado.', 'info')
    return redirect(url_for('index'))

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Nenhum arquivo selecionado', 'warning')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Nenhum arquivo selecionado', 'warning')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            try:
                file.save(filepath)
                flash(f'Arquivo {filename} enviado com sucesso!', 'info')
                # init_db() # Chamado no início da função process_and_load_excel
                success, message = process_and_load_excel(filepath)
                if success:
                    flash(f'Arquivo processado: {message}', 'success')
                else:
                    flash(f'Erro ao processar arquivo: {message}', 'danger')
            except Exception as e:
                logger.exception(f"Erro ao salvar/processar upload: {e}")
                flash(f'Erro crítico ao salvar ou processar o arquivo: {e}', 'danger')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Tipo de arquivo não permitido. Use .xlsx', 'danger')
            return redirect(request.url)

    # Método GET
    init_db() # Garante que a tabela exista ao carregar o dashboard
    dashboard_data = get_dashboard_data()
    admin_template = 'admin_chart_enhanced.html' if os.path.exists(os.path.join(app.template_folder, 'admin_chart_enhanced.html')) else 'admin.html'
    logger.info(f"Renderizando template: {admin_template} com dados: {dashboard_data.keys()}")
    return render_template(admin_template, data=dashboard_data)

# --- API para Chatbot ---
@app.route('/api/chat', methods=['POST'])
def chat_api():
    user_message = request.json.get('message')
    if not user_message:
        return jsonify({'reply': 'Por favor, envie uma mensagem.'})

    logger.info(f"Mensagem recebida do chatbot: {user_message}")
    reply = "Desculpe, não consegui processar sua pergunta. Por favor, tente reformular ou entre em contato com os compradores Miriam ou Irineu."
    conn = get_db()
    if not conn:
         return jsonify({'reply': 'Erro interno ao conectar ao banco de dados. Tente novamente mais tarde.'}), 500

    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='solicitacoes'")
        if not cursor.fetchone():
             logger.warning("Chatbot: Tabela 'solicitacoes' não encontrada.")
             return jsonify({'reply': 'A base de dados ainda não foi carregada. Peça ao administrador para fazer o upload da planilha.'})

        # Verificar se a tabela está vazia
        cursor.execute("SELECT COUNT(*) FROM solicitacoes")
        if cursor.fetchone()[0] == 0:
            logger.info("Chatbot: Tabela 'solicitacoes' está vazia.")
            return jsonify({'reply': 'A base de dados foi carregada, mas está vazia no momento. Peça ao administrador para fazer o upload da planilha com dados.'})

        # 1. Verificar status da solicitação X
        match_status = re.search(r'(?:status|estado)\s+(?:da\s+)?(?:solicitação|solicitacao|pedido)\s+(\w+)', user_message, re.IGNORECASE)
        if match_status:
            solicitacao_id = match_status.group(1)
            logger.info(f"Buscando status da solicitação: {solicitacao_id}")
            cursor.execute("SELECT Status, Etapa, Comprador FROM solicitacoes WHERE Solicitacao = ?", (solicitacao_id,))
            result = cursor.fetchone()
            if result:
                reply = f"Olá! A solicitação {solicitacao_id} está no status '{result['Status']}' e na etapa '{result['Etapa']}'. O comprador responsável é {result['Comprador']}."
            else:
                reply = f"Olá! Não encontrei a solicitação {solicitacao_id}. Poderia verificar o número? Se precisar de ajuda, fale com Miriam ou Irineu."

        # 2. Quantas solicitações estão pendentes?
        elif re.search(r'(?:quantas|numero de)\s+(?:solicitações|solicitacoes|pedidos)\s+(?:estão|estao)\s+pendentes', user_message, re.IGNORECASE):
            logger.info("Buscando número de solicitações pendentes")
            cursor.execute("SELECT COUNT(*) FROM solicitacoes WHERE Status NOT IN ('aprovado', 'finalizado', 'cancelado', 'não aprovado')")
            count = cursor.fetchone()[0]
            reply = f"Atualmente, há {count} solicitações consideradas pendentes (que não estão aprovadas, finalizadas ou canceladas)."

        # 3. Quais solicitações estão com mais de X dias de atraso?
        match_atraso = re.search(r'(?:quais|listar)\s+(?:solicitações|solicitacoes|pedidos)\s+(?:com|com mais de|acima de)\s+(\d+)\s+dias\s+(?:de\s+)?(?:atraso|atrasadas)', user_message, re.IGNORECASE)
        if match_atraso:
            dias_atraso = int(match_atraso.group(1))
            logger.info(f"Buscando solicitações com mais de {dias_atraso} dias de atraso (DiasAtrSol)")
            cursor.execute("SELECT Solicitacao, Comprador, DiasAtrSol FROM solicitacoes WHERE DiasAtrSol > ? ORDER BY DiasAtrSol DESC", (dias_atraso,))
            results = cursor.fetchall()
            if results:
                reply = f"Encontrei {len(results)} solicitações com mais de {dias_atraso} dias de atraso (na coluna 'Dias Atr Sol'):\n"
                reply += "\n".join([f"- Solicitação {r['Solicitacao']} ({r['Comprador']}): {r['DiasAtrSol']} dias" for r in results])
            else:
                reply = f"Ótimo! Não há solicitações com mais de {dias_atraso} dias de atraso (na coluna 'Dias Atr Sol') no momento."

        else:
            reply = ("Olá! 😊 Não entendi bem sua pergunta. Que tal tentar algo como:\n" 
                     "- `status da solicitação 12345`\n" 
                     "- `quantas solicitações estão pendentes?`\n" 
                     "- `listar pedidos com mais de 7 dias de atraso`\n\n" 
                     "Se precisar de algo diferente, por favor, fale com os super compradores Miriam ou Irineu! Eles podem ajudar.")

    except sqlite3.Error as e:
        logger.error(f"Erro ao consultar o banco de dados para o chatbot: {e}")
        reply = "Tive um problema ao buscar as informações no banco de dados. Por favor, tente novamente ou contate Miriam ou Irineu."
        return jsonify({'reply': reply}), 500
    except Exception as e:
        logger.exception(f"Erro inesperado na API do chatbot: {e}")
        reply = "Ocorreu um erro inesperado ao processar sua solicitação. Por favor, contate Miriam ou Irineu."
        return jsonify({'reply': reply}), 500
    finally:
        if conn:
            conn.close()

    return jsonify({'reply': reply})


# --- Inicialização ---
# Garante que o DB e a tabela existam na inicialização
# Executa isso antes de qualquer request para evitar erros no primeiro acesso
with app.app_context():
    init_db()

if __name__ == '__main__':
    logger.info(f"Servidor Flask pronto para iniciar em host 0.0.0.0 porta 5000")
    # O Gunicorn/Waitress será usado em produção pelo Railway
    # app.run(host='0.0.0.0', port=5000, debug=False)

