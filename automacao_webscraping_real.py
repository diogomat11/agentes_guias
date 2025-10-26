#!/usr/bin/env python3
"""
Automação Real baseada em ImportBaseGuias.py
- Sem macros/Excel: origem das carteirinhas vem do banco
- Armazenamento direto em baseguias (upsert)
"""

import time
import datetime
import logging
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import List
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from automacao_carteirinhas import DatabaseManager

# Carregar variáveis de ambiente para suportar execução direta deste módulo
load_dotenv()

# Estado global mínimo (mantendo padrão do ImportBaseGuias.py)
driver = None
Benef_cart = None
arrterapias = [0] * 8
db_manager = None

def get_supabase_client() -> Client | None:
    """Inicializa cliente Supabase via REST para fallback de persistência."""
    try:
        load_dotenv()
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        if supabase_url and supabase_key:
            return create_client(supabase_url, supabase_key)
    except Exception as e:
        logging.getLogger(__name__).error(f"Falha ao inicializar cliente Supabase: {e}")
    return None

def get_db_manager():
    """Inicializa o DatabaseManager sob demanda para evitar falhas na importação."""
    global db_manager
    if db_manager is None:
        try:
            db_manager = DatabaseManager()
        except Exception as e:
            logging.getLogger(__name__).error(f"Falha ao inicializar DatabaseManager: {e}")
            db_manager = None
    return db_manager

class ByWrapper:
    def ID(self, id_val):
        return (By.ID, id_val)
    def XPath(self, xpath_val):
        return (By.XPATH, xpath_val)
    def linktext(self, text):
        return (By.LINK_TEXT, text)

oCheck = ByWrapper()

def is_element_present(driver, by_locator, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located(by_locator))
        return True
    except TimeoutException:
        return False

def funccarteira(carteira, Retorno):
    try:
        p1, resto = carteira.split('.', 1)
        p2, resto = resto.split('.', 1)
        p3, resto = resto.split('.', 1)
        if '-' in resto:
            p4, p5 = resto.split('-', 1)
        else:
            p4, p5 = resto, ""
    except Exception:
        return ""
    p1, p2, p3, p4, p5 = p1.strip(), p2.strip(), p3.strip(), p4.strip(), p5.strip()
    return {1: p1, 2: p2, 3: p3, 4: p4, 5: p5}.get(Retorno, "")

def parse_date_br(s: str):
    try:
        s = (s or "").strip().split()[0]
        if not s:
            return None
        return datetime.datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        return None

def to_int_safe(s: str):
    try:
        s = (s or "").strip()
        if not s:
            return None
        return int(s)
    except Exception:
        return None

def to_db_date(d):
    try:
        if isinstance(d, datetime.date):
            return d.isoformat()
        if isinstance(d, datetime.datetime):
            return d.date().isoformat()
    except Exception:
        pass
    return None

def validCode(cod_terminologia: str) -> int:
    global arrterapias
    if cod_terminologia == "2250005103" and arrterapias[0] < 1500:
        return 1
    if cod_terminologia == "2250005111" and arrterapias[1] < 1500:
        return 2
    if cod_terminologia == "2250005189" and arrterapias[2] < 1500:
        return 3
    if cod_terminologia == "2250005170" and arrterapias[3] < 1500:
        return 4
    if cod_terminologia == "2250005278" and arrterapias[4] < 1500:
        return 5
    if cod_terminologia.startswith("50001213") and arrterapias[5] < 1500:
        return 6
    if cod_terminologia.startswith("50000012") and arrterapias[6] < 1500:
        return 7
    return 0

def upsert_guia_no_banco(guia_data: dict):
    try:
        manager = get_db_manager()
        if manager:
            try:
                check_query = "SELECT id FROM baseguias WHERE carteirinha = %s AND guia = %s"
                existing = manager.execute_query(check_query, (guia_data['carteirinha'], guia_data['guia']), fetch=True)
                if existing:
                    update_query = (
                        "UPDATE baseguias SET "
                        "paciente = %s, data_autorizacao = %s, senha = %s, validade = %s, "
                        "codigo_terapia = %s, qtde_solicitado = %s, sessoes_autorizadas = %s, "
                        "updated_at = CURRENT_TIMESTAMP WHERE carteirinha = %s AND guia = %s"
                    )
                    params = (
                        guia_data['paciente'],
                        to_db_date(guia_data['data_autorizacao']),
                        guia_data['senha'],
                        to_db_date(guia_data['validade']),
                        guia_data['codigo_terapia'],
                        guia_data['qtde_solicitado'],
                        guia_data['sessoes_autorizadas'],
                        guia_data['carteirinha'],
                        guia_data['guia']
                    )
                    manager.execute_query(update_query, params)
                    return "updated"
                else:
                    insert_query = (
                        "INSERT INTO baseguias (carteirinha, paciente, guia, data_autorizacao, senha, validade, "
                        "codigo_terapia, qtde_solicitado, sessoes_autorizadas, created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                    params = (
                        guia_data['carteirinha'],
                        guia_data['paciente'],
                        guia_data['guia'],
                        to_db_date(guia_data['data_autorizacao']),
                        guia_data['senha'],
                        to_db_date(guia_data['validade']),
                        guia_data['codigo_terapia'],
                        guia_data['qtde_solicitado'],
                        guia_data['sessoes_autorizadas']
                    )
                    manager.execute_query(insert_query, params)
                    return "inserted"
            except Exception as db_err:
                print(f"Falha no SQL direto, tentando Supabase REST: {db_err}")

        # Fallback via Supabase REST (HTTP), quando conexão direta ao Postgres falhar
        supa = get_supabase_client()
        if not supa:
            print("Banco indisponível para upsert (sem Supabase REST).")
            return "db_unavailable"

        payload = {
            'carteirinha': guia_data['carteirinha'],
            'paciente': guia_data['paciente'],
            'guia': guia_data['guia'],
            'data_autorizacao': to_db_date(guia_data['data_autorizacao']),
            'senha': guia_data['senha'],
            'validade': to_db_date(guia_data['validade']),
            'codigo_terapia': guia_data['codigo_terapia'],
            'qtde_solicitado': guia_data['qtde_solicitado'],
            'sessoes_autorizadas': guia_data['sessoes_autorizadas']
        }

        try:
            # Verificar existência
            sel = supa.table("baseguias").select("id").eq("carteirinha", payload['carteirinha']).eq("guia", payload['guia']).limit(1).execute()
            if sel.data:
                supa.table("baseguias").update(payload).eq("carteirinha", payload['carteirinha']).eq("guia", payload['guia']).execute()
                return "updated"
            else:
                supa.table("baseguias").insert(payload).execute()
                return "inserted"
        except Exception as rest_err:
            print(f"Erro no fallback Supabase REST: {rest_err}")
            return "error"
    except Exception as e:
        print(f"Erro ao upsert guia: {e}")
        return "error"

def importGuia(driver, lin):
    global Benef_cart
    cod_terminologia = ""
    try:
        classguia_elements = driver.find_elements(By.CLASS_NAME, "MagnetoDataTD")
    except Exception as e:
        print("Erro ao obter elementos:", e)
        return
    countitem = 0
    cappen = False
    for element in classguia_elements:
        countitem += 1
        if countitem == 3:
            cod_terminologia = element.text[:10]
            cappen = bool(validCode(cod_terminologia))
        if countitem == 6:
            if cappen:
                try:
                    if is_element_present(driver, oCheck.XPath('//*[@id="Button_Voltar"]')):
                        NewCarteira = driver.find_element(By.XPATH, '//*[@id="conteudo-submenu"]/form/table/tbody/tr[1]/td[2]')
                        textCarteira = NewCarteira.text
                        col1_value = textCarteira[:21]
                        col2_value = textCarteira[24:]
                        NewNumGuia = driver.find_element(By.XPATH, '//*[@id="conteudo-submenu"]/form/table/tbody/tr[3]/td[2]')
                        DataAuthorize = driver.find_element(By.XPATH, '//*[@id="conteudo-submenu"]/form/table/tbody/tr[4]/td[4]')
                        NewSenha = driver.find_element(By.XPATH, '//*[@id="conteudo-submenu"]/form/table/tbody/tr[5]/td[2]')
                        DataValid = driver.find_element(By.XPATH, '//*[@id="CampoValidadeSenha"]')
                        NewCodTerapia = driver.find_element(By.XPATH, '/html/body/div[1]/div[13]/div/table/tbody/tr[2]/td[3]/input')
                        QtdeSolicitado = driver.find_element(By.XPATH, '/html/body/div[1]/div[13]/div/table/tbody/tr[2]/td[5]')
                        QtdeAutorizado = driver.find_element(By.XPATH, '/html/body/div[1]/div[13]/div/table/tbody/tr[2]/td[6]')

                        guia_dict = {
                            'carteirinha': col1_value,
                            'paciente': col2_value,
                            'guia': str(NewNumGuia.text).strip(),
                            'data_autorizacao': parse_date_br(DataAuthorize.text),
                            'senha': (NewSenha.text or '').strip(),
                            'validade': parse_date_br(DataValid.text or DataValid.get_attribute("value")),
                            'codigo_terapia': (NewCodTerapia.get_attribute("value") or '').strip(),
                            'qtde_solicitado': to_int_safe(QtdeSolicitado.text),
                            'sessoes_autorizadas': to_int_safe(QtdeAutorizado.text)
                        }
                        status = upsert_guia_no_banco(guia_dict)
                        print(f"Guia {guia_dict['guia']} - {status}")
                        driver.execute_script("window.scrollBy(0, 100);")
                        btnVoltar = driver.find_element(By.XPATH, '//*[@id="Button_Voltar"]')
                        btnVoltar.click()
                        return
                except Exception as e:
                    print("Erro ao extrair guia:", e)
                    return
            else:
                try:
                    time.sleep(1)
                    btnVoltar = driver.find_element(By.XPATH, '//*[@id="Button_Voltar"]')
                    btnVoltar.click()
                except Exception:
                    pass
                return
    if countitem == 0:
        try:
            time.sleep(1)
            btnVoltar = driver.find_element(By.XPATH, '//*[@id="Button_Voltar"]')
            btnVoltar.click()
            time.sleep(1)
        except Exception:
            pass

def captura(driver):
    global Benef_cart, arrterapias
    x1 = funccarteira(Benef_cart, 1)
    x2 = funccarteira(Benef_cart, 2)
    x3 = funccarteira(Benef_cart, 3)
    x4 = funccarteira(Benef_cart, 4)
    x5 = funccarteira(Benef_cart, 5)

    if x1 != "0064":
        # Após abrir a aba das guias, par   a carteirinhas sem prefixo 0064,
        # é necessário atualizar a página e aguardar o botão "Atualizar".
        time.sleep(5)
        drvurl = driver.current_url
        driver.get(drvurl)
        time.sleep(2)
        appeared = False
        # Tenta aguardar até 5s, verificando a cada 1s
        for _ in range(5):
            if is_element_present(driver, oCheck.XPath('//*[@id="Button_Update"]'), timeout=1):
                appeared = True
                break
            time.sleep(1)
        # Se não apareceu, tenta múltiplas estratégias de navegação forçada
        if not appeared:
            try:
                # 1) via JS assign (simula digitar URL e Enter)
                driver.execute_script("window.location.assign(arguments[0]);", drvurl)
                time.sleep(3)
                for _ in range(5):
                    if is_element_present(driver, oCheck.XPath('//*[@id="Button_Update"]'), timeout=1):
                        appeared = True
                        break
                    time.sleep(1)
            except Exception as e:
                print(f"Falha em window.location.assign: {e}")
        if not appeared:
            try:
                # 2) cache-buster com replace
                ts = str(int(time.time()))
                sep = '&' if '?' in drvurl else '?'
                url_cb = f"{drvurl}{sep}ts={ts}"
                driver.execute_script("window.location.replace(arguments[0]);", url_cb)
                time.sleep(3)
                for _ in range(5):
                    if is_element_present(driver, oCheck.XPath('//*[@id="Button_Update"]'), timeout=1):
                        appeared = True
                        break
                    time.sleep(1)
            except Exception as e:
                print(f"Falha em window.location.replace: {e}")
        if not appeared:
            try:
                # 3) abrir nova aba e alternar
                driver.execute_script("window.open(arguments[0], '_blank');", drvurl)
                driver.switch_to.window(driver.window_handles[-1])
                time.sleep(3)
                for _ in range(5):
                    if is_element_present(driver, oCheck.XPath('//*[@id="Button_Update"]'), timeout=1):
                        appeared = True
                        break
                    time.sleep(1)
            except Exception as e:
                print(f"Falha ao abrir nova aba para reload: {e}")
        if not appeared:
            print("Botão 'Atualizar' não apareceu após tentativas (pré-consulta); seguindo para consulta do paciente.")
        else:
            try:
                btn_atualiza = driver.find_element(By.XPATH, '//*[@id="Button_Update"]')
                btn_atualiza.click()
            except Exception:
                pass

    if is_element_present(driver, oCheck.XPath('//*[@id="Button_Consulta"]')):
        drvurl = driver.current_url
        driver.get(drvurl)
        time.sleep(5)
        consultabenef = driver.find_element(By.XPATH, '//*[@id="Button_Consulta"]')
        consultabenef.click()
        time.sleep(1)
        DT_VALIDADE_CARTAO = driver.find_element(By.XPATH, '//*[@id="DT_VALIDADE_CARTAO"]')
        DataValid = DT_VALIDADE_CARTAO.get_attribute("value")
        try:
            data_valid_date = datetime.datetime.strptime(DataValid, "%d/%m/%Y")
        except Exception:
            data_valid_date = datetime.datetime.now()
        if data_valid_date < datetime.datetime.now():
            x_date = (datetime.datetime.now() + datetime.timedelta(days=365)).strftime("%d/%m/%Y")
            DT_VALIDADE_CARTAO.click()
            time.sleep(1)
            driver.execute_script("document.getElementById('DT_VALIDADE_CARTAO').removeAttribute('readonly')")
            DT_VALIDADE_CARTAO.clear()
            DT_VALIDADE_CARTAO.send_keys(x_date)
        time.sleep(1)
        if x1 != "0064":
            appeared = False
            # 1) Tenta aguardar até 5s pelo botão
            for _ in range(5):
                if is_element_present(driver, oCheck.XPath('//*[@id="Button_Update"]'), timeout=1):
                    appeared = True
                    break
                time.sleep(1)
            # 2) driver.refresh()
            if not appeared:
                try:
                    driver.refresh()
                    time.sleep(2)
                    for _ in range(5):
                        if is_element_present(driver, oCheck.XPath('//*[@id="Button_Update"]'), timeout=1):
                            appeared = True
                            break
                        time.sleep(1)
                except Exception:
                    pass
            # 3) JS history.go(0)
            if not appeared:
                try:
                    driver.execute_script('history.go(0)')
                    time.sleep(2)
                    for _ in range(5):
                        if is_element_present(driver, oCheck.XPath('//*[@id="Button_Update"]'), timeout=1):
                            appeared = True
                            break
                        time.sleep(1)
                except Exception:
                    pass
            # 4) Enviar tecla F5
            if not appeared:
                try:
                    from selenium.webdriver.common.keys import Keys
                    from selenium.webdriver import ActionChains
                    ActionChains(driver).send_keys(Keys.F5).perform()
                    time.sleep(2)
                    for _ in range(5):
                        if is_element_present(driver, oCheck.XPath('//*[@id="Button_Update"]'), timeout=1):
                            appeared = True
                            break
                        time.sleep(1)
                except Exception:
                    pass
            if not appeared:
                print("Botão 'Atualizar' não apareceu após tentativas (pós-consulta).")
            else:
                try:
                    btn_atualiza = driver.find_element(By.XPATH, '//*[@id="Button_Update"]')
                    btn_atualiza.click()
                except Exception:
                    pass
        else:
            btn_atualiza = driver.find_element(By.XPATH, '//*[@id="Button_Update"]')
            btn_atualiza.click()

    countwait = 0
    while not is_element_present(driver, oCheck.XPath('//*[@id="s_NR_GUIA"]')):
        time.sleep(1)
        countwait += 1
        if countwait > 20:
            print("Erro de internet ou não foi liberado acesso às Guias do paciente")
            return

    arrterapias = [0] * 8
    time.sleep(2)

    try:
        if is_element_present(driver, oCheck.XPath('//*[@id="conteudo-submenu"]/table[2]/tbody/tr[1]/td[1]/a')):
            DataClassific = driver.find_element(By.XPATH, '//*[@id="conteudo-submenu"]/table[2]/tbody/tr[1]/td[1]/a')
            DataClassific.click()
            time.sleep(4)
            DataClassific = driver.find_element(By.XPATH, '//*[@id="conteudo-submenu"]/table[2]/tbody/tr[1]/td[1]/a')
            DataClassific.click()
        time.sleep(2)

        while True:
            time.sleep(2)
            try:
                DataTable = driver.find_element(By.XPATH, '//*[@id="conteudo-submenu"]/table[2]')
                linhas = DataTable.find_elements(By.TAG_NAME, "tr")
                x_count = len(linhas)
                for idx in range(1, x_count - 1):
                    try:
                        elemento_span = driver.find_element(By.XPATH, f'//*[@id="conteudo-submenu"]/table[2]/tbody/tr[{idx+1}]/td[6]/span')
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento_span)
                        time.sleep(1)
                        if elemento_span.text == "Autorizado":
                            DataSolicit = driver.find_element(By.XPATH, f'//*[@id="conteudo-submenu"]/table[2]/tbody/tr[{idx+1}]/td[1]')
                            data_texto = DataSolicit.text.strip()
                            try:
                                dataPEI = datetime.datetime.strptime(data_texto, "%d/%m/%Y").date()
                            except Exception:
                                dataPEI = datetime.datetime.now().date()
                            IniCompDate = datetime.datetime.now().date() - datetime.timedelta(days=270)
                            if dataPEI < IniCompDate:
                                return
                            guia_link = driver.find_element(By.XPATH, f'//*[@id="conteudo-submenu"]/table[2]/tbody/tr[{idx+1}]/td[4]/a')
                            guia_link.click()
                            time.sleep(2)
                            importGuia(driver, idx+1)
                    except Exception as e:
                        print(f"Erro ao processar linha {idx + 1}: {str(e)}")
                        continue
                if is_element_present(driver, oCheck.linktext("Próxima")):
                    NUM_PAGE = driver.find_element(By.LINK_TEXT, "Próxima")
                    NUM_PAGE.click()
                    time.sleep(2)
                else:
                    break
            except Exception as e:
                print(f"Erro ao processar tabela: {str(e)}")
                break
    except Exception as e:
        print(f"Erro na função captura: {str(e)}")

def obter_carteirinhas_por_modo(modo: str = 'todos', carteirinha: str = None, data_inicial: str = None, data_final: str = None) -> List[str]:
    try:
        if modo == 'unico' and carteirinha:
            return [carteirinha.strip()]
        if modo == 'intervalo' and data_inicial and data_final:
            manager = get_db_manager()
            if not manager:
                print("Banco indisponível para obter carteirinhas.")
                return []
            q = (
                "SELECT DISTINCT a.carteirinha "
                "FROM agendamentos a "
                "JOIN carteirinhas c ON c.carteiras = a.carteirinha "
                "WHERE a.data BETWEEN %s AND %s "
                "AND a.carteirinha IS NOT NULL "
                "AND COALESCE(c.status,'') ILIKE 'ativo'"
            )
            rows = manager.execute_query(q, (data_inicial, data_final), fetch=True)
            return [r[0] for r in rows if r and r[0]]
        manager = get_db_manager()
        if not manager:
            print("Banco indisponível para obter carteirinhas.")
            return []
        q = "SELECT DISTINCT carteiras FROM carteirinhas WHERE COALESCE(status,'') ILIKE 'ativo'"
        rows = manager.execute_query(q, (), fetch=True)
        return [r[0] for r in rows if r and r[0]]
    except Exception as e:
        print(f"Erro ao obter carteirinhas por modo: {e}")
        return []

def ConsultGuias(driver, carteirinhas_list: List[str]):
    global Benef_cart
    total_rows = len(carteirinhas_list)
    print("Total de carteiras a processar:", total_rows)
    for i, Benef_cart in enumerate(carteirinhas_list, start=2):
        try:
            if not Benef_cart:
                print(f"Linha {i}: Carteira vazia, pulando...")
                continue
            print(f"\nProcessando linha {i}, carteira: {Benef_cart}")
            x1 = funccarteira(Benef_cart, 1)
            x2 = funccarteira(Benef_cart, 2)
            x3 = funccarteira(Benef_cart, 3)
            x4 = funccarteira(Benef_cart, 4)
            x5 = funccarteira(Benef_cart, 5)
            CountTry = 0
            while CountTry < 3:
                try:
                    if is_element_present(driver, oCheck.XPath('//*[@id="cadastro_biometria"]/div/div[2]/span'), timeout=3):
                        new_exame = driver.find_element(By.XPATH, '//*[@id="cadastro_biometria"]/div/div[2]/span')
                        new_exame.click()
                        time.sleep(2)
                        driver.switch_to.window(driver.window_handles[-1])
                        driver.maximize_window()
                        cartCompleto = x1 + x2 + x3 + x4 + x5
                        cartaoParcial = x2 + x3 + x4 + x5
                        element7 = driver.find_element(By.NAME, 'nr_via')
                        element6 = driver.find_element(By.NAME, 'DS_CARTAO')
                        element3 = driver.find_element(By.NAME, 'CD_DEPENDENCIA')
                        driver.execute_script("arguments[0].setAttribute('type', 'text');", element7)
                        time.sleep(1)
                        element7.send_keys(cartCompleto)
                        driver.execute_script("arguments[0].setAttribute('type', 'text');", element6)
                        time.sleep(1)
                        element6.send_keys(cartaoParcial)
                        driver.execute_script("arguments[0].setAttribute('type', 'text');", element3)
                        time.sleep(1)
                        element3.send_keys(x3)
                        captura(driver)
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                        break
                    else:
                        driver.refresh()
                        time.sleep(2)
                        CountTry += 1
                except Exception as e:
                    print(f"Erro na tentativa {CountTry + 1}:", str(e))
                    CountTry += 1
                    if CountTry >= 3:
                        print(f"Falha após 3 tentativas para carteira {Benef_cart}")
                        driver.switch_to.window(driver.window_handles[0])
                        break
                    time.sleep(2)
        except Exception as e:
            print(f"Erro ao processar carteira {Benef_cart}:", str(e))
            continue
    print("\nProcessamento finalizado")
    driver.quit()

def SGUCARD(modo: str = 'todos', carteirinha: str = None, data_inicial: str = None, data_final: str = None):
    global driver
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-infobars")
    # Ativar modo headless conforme variável de ambiente
    headless_env = (os.getenv("SGUCARD_HEADLESS", "false") or "false").strip().lower()
    if headless_env in ("1", "true", "yes", "on"): 
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=chrome_options)
    time.sleep(3)
    driver.get("https://sgucard.unimedgoiania.coop.br/cmagnet/Login.do")
    try:
        driver.maximize_window()
    except Exception:
        pass
    while not is_element_present(driver, oCheck.ID("passwordTemp"), timeout=3):
        time.sleep(1)
    login_elem = driver.find_element(By.ID, "login")
    passwordTemp = driver.find_element(By.ID, "passwordTemp")
    Button_DoLogin = driver.find_element(By.ID, "Button_DoLogin")
    login_elem.send_keys("REC2209525")
    time.sleep(1)
    passwordTemp.clear()
    passwordTemp.send_keys("Unimed@2025")
    Button_DoLogin.click()
    time.sleep(4)
    lista = obter_carteirinhas_por_modo(modo, carteirinha, data_inicial, data_final)
    ConsultGuias(driver, lista)

class WebScrapingRealAutomacao:
    def executar_automacao_completa(self, filtro_api: str = "manual", carteira: str = None, data_inicio: str = None, data_fim: str = None) -> dict:
        """Interface compatível com automacao_carteirinhas.vasculhar_carteirinhas.
        Executa o SGUCARD conforme o filtro e retorna resumo.
        """
        start_ts = time.time()
        try:
            # Mapear o filtro para o modo usado em SGUCARD/obter_carteirinhas_por_modo
            if filtro_api == "manual" and carteira:
                modo = "unico"
            elif filtro_api == "intervalo" and data_inicio and data_fim:
                modo = "intervalo"
            else:
                modo = "todos"

            # Pré-contar carteirinhas a serem processadas
            try:
                lista = obter_carteirinhas_por_modo(modo, carteira, data_inicio, data_fim)
                count_carteirinhas = len(lista)
            except Exception:
                count_carteirinhas = 0

            # Executa automação real (abre Chrome respeitando SGUCARD_HEADLESS)
            SGUCARD(modo=modo, carteirinha=carteira, data_inicial=data_inicio, data_final=data_fim)

            elapsed = int(time.time() - start_ts)
            hh = elapsed // 3600
            mm = (elapsed % 3600) // 60
            ss = elapsed % 60
            return {
                "sucesso": True,
                "carteirinhas_processadas": count_carteirinhas,
                # Sem contador de guias no fluxo atual; retornamos 0 por ora
                "guias_extraidas": 0,
                "tempo_execucao": f"{hh:02d}:{mm:02d}:{ss:02d}"
            }
        except Exception as e:
            return {
                "sucesso": False,
                "erro": str(e),
                "carteirinhas_processadas": 0,
                "guias_extraidas": 0,
                "tempo_execucao": "00:00:00"
            }

if __name__ == "__main__":
    SGUCARD('unico', '0064.2959.000015.11-1')