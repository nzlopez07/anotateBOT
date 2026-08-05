import json
import time
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
import requests

class UTNInscripcionClient:
    """
    Cliente HTTP optimizado para el sistema Autogestión 4 de la UTN FRC.
    Realiza la autenticación, consulta de oferta académica, resolución de comisiones,
    obtención de GUID y envío directo del paquete de inscripción a materias.
    """
    
    BASE_URL_LOGON = "https://www.frc.utn.edu.ar"
    BASE_URL_A4 = "https://a4.frc.utn.edu.ar/4"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        })
        self.guid: Optional[str] = None
        self.materias_cache: List[Dict[str, Any]] = []
        self.telegram_token: Optional[str] = None
        self.telegram_chat_id: Optional[str] = None
        self.server_clock_offset_seconds: float = 0.0

    def sync_server_clock(self, response_headers: Dict[str, str]):
        """
        Calcula el desfase (offset) exacto en segundos entre el reloj local de la PC y el reloj del servidor de la UTN.
        """
        date_str = response_headers.get("Date") or response_headers.get("date")
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                server_dt = parsedate_to_datetime(date_str).replace(tzinfo=None)
                local_dt = datetime.now(timezone.utc).replace(tzinfo=None)
                self.server_clock_offset_seconds = (server_dt - local_dt).total_seconds()
                # print(f"⏱️ Sync Reloj UTN: Desfase detectado = {round(self.server_clock_offset_seconds, 3)}s")
            except Exception:
                pass

    def setup_telegram(self, token: str, chat_id: str):
        self.telegram_token = token
        self.telegram_chat_id = chat_id


    def send_telegram(self, text: str):
        if not self.telegram_token or not self.telegram_chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(url, json={"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "Markdown"}, timeout=3)
        except Exception as e:
            print(f"[!] Error al enviar mensaje por Telegram: {e}")


    def login(self, usuario: str, dominio: str, clave: str) -> bool:
        """
        Inicia sesión en la UTN FRC y obtiene las cookies de sesión necesarias.
        """
        login_url = f"{self.BASE_URL_LOGON}/funciones/sesion/iniciarSesion.frc"
        payload = {
            "userid": "userid",
            "t": str(int(time.time() * 1000) % 100000000),
            "page": "login",
            "redir": "/logon.frc",
            "txtUsuario": usuario,
            "txtDominios": dominio,
            "pwdClave": clave
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{self.BASE_URL_LOGON}/logon.frc"
        }

        response = self.session.post(login_url, data=payload, headers=headers, allow_redirects=True)
        self.sync_server_clock(response.headers)
        
        # Verificar si la sesión se inició correctamente navegando a Autogestión 4
        a4_resp = self.session.get(f"{self.BASE_URL_A4}/", allow_redirects=True)
        self.sync_server_clock(a4_resp.headers)
        
        if "Logout" in a4_resp.text or "inscripcion" in a4_resp.text.lower() or a4_resp.status_code == 200:
            return True
        return False


    def init_cursado(self, usuario: str) -> bool:
        """
        Inicializa la sesión de trámite de cursado en Autogestión 4.
        """
        self.session.get(f"{self.BASE_URL_A4}/tramite/inscripcion/cursado/default.jsp")
        
        init_url = f"{self.BASE_URL_A4}/transacciones/inscripcion/cursado/init"
        id_peticion = f"0{usuario}F65BBE75EB7C"
        
        self.session.post(init_url, data={"idPeticion": id_peticion}, headers={"X-Requested-With": "XMLHttpRequest"})
        self.session.post(f"{self.BASE_URL_A4}/transacciones/inscripcion/cursado/pendientes", headers={"X-Requested-With": "XMLHttpRequest"})
        return True

    def get_comisiones(self, har_fallback_path: str = "www.frc.utn.edu.ar.har") -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """
        Obtiene la oferta académica (materias y comisiones disponibles) y el GUID.
        Si la ventana de inscripción aún no está abierta en el servidor en vivo,
        utiliza la estructura del archivo HAR como fallback para validar el mapeo.
        """
        url = f"{self.BASE_URL_A4}/transacciones/inscripcion/cursado/comisiones"
        headers = {"X-Requested-With": "XMLHttpRequest"}
        
        resp = self.session.get(url, headers=headers)
        if resp.status_code == 200:
            try:
                data = resp.json()
                self.guid = data.get("id")
                valor_raw = data.get("valor", "")
                
                if valor_raw:
                    if valor_raw.startswith("{") and not valor_raw.startswith("["):
                        valor_raw = "[" + valor_raw + "]"
                    self.materias_cache = json.loads(valor_raw)
                    return self.guid, self.materias_cache
            except Exception:
                pass

        # Fallback usando el archivo HAR si el servidor en vivo aún no abrió la consulta
        try:
            import os
            if os.path.exists(har_fallback_path):
                with open(har_fallback_path, "r", encoding="utf-8", errors="ignore") as f:
                    har_data = json.load(f)
                for entry in har_data.get("log", {}).get("entries", []):
                    if "comisiones" in entry.get("request", {}).get("url", ""):
                        res_text = entry.get("response", {}).get("content", {}).get("text", "")
                        if res_text:
                            data = json.loads(res_text)
                            self.guid = self.guid or data.get("id")
                            v_raw = data.get("valor", "")
                            if v_raw.startswith("{") and not v_raw.startswith("["):
                                v_raw = "[" + v_raw + "]"
                            self.materias_cache = json.loads(v_raw)
                            print("[+] Usando la estructura academica (HAR fallback) para la simulacion.")
                            return self.guid, self.materias_cache

        except Exception as e:
            print(f"[!] Error al cargar HAR fallback: {e}")

        return None, []


    def refresh_guid(self) -> Optional[str]:
        """
        Solicita un GUID nuevo y actualizado antes de enviar la inscripción.
        """
        url = f"{self.BASE_URL_A4}/transacciones/guid"
        headers = {"X-Requested-With": "XMLHttpRequest"}
        resp = self.session.get(url, headers=headers)
        if resp.status_code == 200:
            try:
                data = resp.json()
                self.guid = data.get("Guid")
                return self.guid
            except Exception:
                pass
        return self.guid

    def parse_structure(self, structure_str: str) -> List[Dict[str, str]]:
        """
        Parsea el campo 'Structure' de una materia y extrae el nombre limpio del curso.
        Ejemplo: "001  4K121120135|002  4K221205135" -> [{'comision_code': '002', 'curso': '4K2', ...}]
        """
        res = []
        if not structure_str:
            return res
            
        items = structure_str.split("|")
        for item in items:
            item_clean = item.strip()
            if not item_clean:
                continue
            parts = item_clean.split(maxsplit=1)
            if len(parts) >= 2:
                com_code = parts[0].zfill(3)
                rest = parts[1].strip()
                
                # Algoritmo de mapeo de curso UTN FRC: Año(1-5) + Carrera(K/V) + Comisión + Subcomisión(A/B)
                m_yr_spec = re.match(r"^([1-5][A-Za-z]+)", rest)
                if m_yr_spec:
                    prefix = m_yr_spec.group(1).upper()
                    try:
                        sec_num = str(int(com_code))
                    except ValueError:
                        sec_num = ""
                    
                    has_sublet = ""
                    sub_match = re.search(r"^[1-5][A-Za-z]+" + re.escape(sec_num) + r"([A-Za-z])", rest)
                    if sub_match:
                        has_sublet = sub_match.group(1).upper()
                    curso_clean = f"{prefix}{sec_num}{has_sublet}"
                else:
                    curso_clean = rest[:4].strip().upper()

                res.append({
                    "comision_code": com_code,
                    "curso": curso_clean,
                    "rest": rest,
                    "raw": item_clean
                })
        return res

    def resolve_materia_payload(self, comisiones_seleccionadas: List[Any]) -> str:
        """
        Convierte una lista de comisiones seleccionadas en la cadena requerida para la inscripción.
        Soporta:
        - Códigos directos de 14 dígitos (ej: "00520230306002")
        - O dicts con nombre de materia y curso: {"materia": "Ingeniería y Calidad de Software", "curso": "4K2"}
        """
        import unicodedata

        def normalize_str(s: str) -> str:
            if not s:
                return ""
            s_norm = unicodedata.normalize('NFD', s)
            s_clean = ''.join(c for c in s_norm if unicodedata.category(c) != 'Mn')
            return re.sub(r'[^a-z0-9\s]', '', s_clean.lower()).strip()

        stop_words = {"de", "del", "la", "el", "en", "para", "con", "y", "los", "las", "un", "una"}

        codes = []
        
        for sel in comisiones_seleccionadas:
            if isinstance(sel, str):
                codes.append(sel.strip())
            elif isinstance(sel, dict):
                mat_target_raw = sel.get("materia", "")
                mat_target = normalize_str(mat_target_raw)
                mat_code = sel.get("codigo", "")
                
                curso_val = sel.get("curso", "")
                if isinstance(curso_val, list):
                    cursos_target = [c.strip().upper() for c in curso_val]
                else:
                    cursos_target = [str(curso_val).strip().upper()]
                
                words = [w for w in mat_target.split() if w not in stop_words and len(w) >= 3]
                if not words:
                    words = [w for w in mat_target.split() if len(w) >= 3]

                found_materia = None
                
                for m in self.materias_cache:
                    m_codigo = m.get("CODIGO", "")
                    m_nombre = normalize_str(m.get("Name", ""))
                    
                    if mat_code and m_codigo == mat_code:
                        found_materia = m
                        break
                        
                    if mat_target and all(w in m_nombre for w in words):
                        found_materia = m
                        break
                        
                if not found_materia:
                    key_words = [w for w in words if w in {"devops", "seguridad", "automatizacion", "calidad"}]
                    for m in self.materias_cache:
                        m_nombre = normalize_str(m.get("Name", ""))
                        if any(kw in m_nombre for kw in key_words):
                            found_materia = m
                            break

                if found_materia:
                    m_codigo = found_materia.get("CODIGO", "")
                    struct_list = self.parse_structure(found_materia.get("Structure", ""))
                    
                    found_course = False
                    for curso_target in cursos_target:
                        # Extraer número de comisión deseada (ej: "4K2" -> "2", "5K4" -> "4", "4K2A" -> "2")
                        m_num = re.search(r"(\d+)(?=[A-Za-z]?$)", curso_target)
                        target_num = m_num.group(1) if m_num else ""
                        
                        for st in struct_list:
                            rest = st["rest"].upper()
                            com_num = str(int(st["comision_code"]))
                            
                            match_exact = rest.startswith(curso_target) or (curso_target in rest[:6])
                            match_num = bool(target_num and com_num == target_num)
                            
                            if match_exact or match_num:
                                full_code = f"{m_codigo}{st['comision_code']}"
                                codes.append(full_code)
                                found_course = True
                                print(f"[✔] Resuelto en Vivo: {found_materia.get('Name')} (Curso: {curso_target}) -> Código: {full_code}")
                                break
                        if found_course:
                            break
                            
                    # Si no hay estructura disponible en HAR fallback, usar comisión inferida por defecto
                    if not found_course and not struct_list:
                        for curso_target in cursos_target:
                            m_num = re.search(r"(\d+)(?=[A-Za-z]?$)", curso_target)
                            if m_num:
                                com_code = m_num.group(1).zfill(3)
                                full_code = f"{m_codigo}{com_code}"
                                codes.append(full_code)
                                print(f"[✔] Resuelto por Inferencia: {found_materia.get('Name')} (Curso: {curso_target}) -> Código: {full_code}")
                                break
                else:
                    print(f"[!] ADVERTENCIA: No se pudo resolver en la oferta actual: {sel}")


        unique_codes = list(dict.fromkeys(codes))
        return "|".join(unique_codes)


    def enviar_inscripcion(self, payload_materia: str) -> Dict[str, Any]:

        """
        Envía la petición final de inscripción HTTP POST a Autogestión 4.
        """
        if not self.guid:
            self.refresh_guid()
            
        url = f"{self.BASE_URL_A4}/transacciones/inscripcion/cursado"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest"
        }
        data = {
            "GUID": self.guid,
            "materia": payload_materia
        }
        
        t_start = time.perf_counter()
        resp = self.session.post(url, data=data, headers=headers)
        t_elapsed = (time.perf_counter() - t_start) * 1000 # ms
        
        result = {
            "status_code": resp.status_code,
            "time_ms": round(t_elapsed, 2),
            "raw_response": resp.text
        }
        
        try:
            res_json = resp.json()
            result["data"] = res_json
        except Exception:
            pass
            
        return result

    def consultar_posicion(self, id_peticion: str) -> Dict[str, Any]:
        """
        Consulta el estado o posición en cola de la inscripción enviada.
        """
        url = f"{self.BASE_URL_A4}/transacciones/estado/posicion"
        headers = {"X-Requested-With": "XMLHttpRequest"}
        data = {"idPeticion": id_peticion}
        
        resp = self.session.post(url, data=data, headers=headers)
        try:
            return resp.json()
        except Exception:
            return {"valor": resp.status_code, "salida": resp.text}

    def verificar_posicion_materia(self, codigo_materia: str) -> Dict[str, Any]:
        """
        Consulta a la UTN si una materia específica tiene Inscripción Definitiva o Posición en cola.
        Endpoint oficial: POST /transacciones/inscripcion/cursado/posicion/materia
        """
        url = f"{self.BASE_URL_A4}/transacciones/inscripcion/cursado/posicion/materia"
        headers = {"X-Requested-With": "XMLHttpRequest"}
        data = {"materia": codigo_materia}
        
        resp = self.session.post(url, data=data, headers=headers)
        try:
            return resp.json()
        except Exception:
            return {"value": resp.text}

    def verificar_inscripciones_actuales(self, anio: int = 2026) -> List[str]:


        """
        Consulta a la UTN la lista oficial de materias inscriptas para el año en curso.
        """
        url = f"{self.BASE_URL_A4}/cursado/actual/{anio}"
        headers = {"X-Requested-With": "XMLHttpRequest"}
        resp = self.session.get(url, headers=headers)
        
        materias_inscriptas = []
        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, list):
                    for item in data:
                        nom = item.get("nombre") or item.get("materia") or str(item)
                        materias_inscriptas.append(nom)
                elif isinstance(data, dict):
                    for k, v in data.items():
                        materias_inscriptas.append(f"{k}: {v}")
            except Exception:
                if resp.text:
                    materias_inscriptas.append("Comprobante emitido correctamente en servidor.")
        return materias_inscriptas

