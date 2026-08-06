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
        Inicia sesión en la UTN FRC replicando el flujo exacto del navegador:
        1. POST AJAX a /logon.frc (crea la sesión en el servidor IIS)
        2. POST formulario a /funciones/sesion/iniciarSesion.frc (SSO redirect a a4)
        """
        try:
            t_val = str(int(time.time() * 1000) % 100000000)
            
            base_payload = {
                "userid": "userid",
                "t": t_val,
                "page": "login",
                "redir": "/logon.frc",
                "txtUsuario": usuario,
                "txtDominios": dominio,
                "pwdClave": clave
            }
            
            # Paso 1: POST AJAX a /logon.frc (como lo hace el JS del navegador)
            ajax_payload = dict(base_payload)
            ajax_payload["btnEnviar"] = "  Iniciar Sesión  "
            
            try:
                self.session.post(
                    f"{self.BASE_URL_LOGON}/logon.frc",
                    data=ajax_payload,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": "https://www.frc.utn.edu.ar",
                        "Referer": f"{self.BASE_URL_LOGON}/logon.frc",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=8
                )
            except Exception:
                pass
            
            # Paso 2: POST formulario a iniciarSesion.frc (sin X-Requested-With, genera redirect SSO)
            response = self.session.post(
                f"{self.BASE_URL_LOGON}/funciones/sesion/iniciarSesion.frc",
                data=base_payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://www.frc.utn.edu.ar",
                    "Referer": f"{self.BASE_URL_LOGON}/logon.frc",
                },
                allow_redirects=True,
                timeout=10
            )
            self.sync_server_clock(response.headers)
            
            # Verificar que terminamos en a4 (no en www/logon con error)
            final_url = response.url
            if "a4.frc.utn.edu.ar" in final_url:
                return True
            
            # Fallback: intentar navegar a a4 directamente
            a4_resp = self.session.get(f"{self.BASE_URL_A4}/", allow_redirects=True, timeout=10)
            self.sync_server_clock(a4_resp.headers)
            
            if "a4.frc.utn.edu.ar" in a4_resp.url:
                return True
            return False
        except Exception:
            return False


    REFERER_CURSADO = f"{BASE_URL_A4}/tramite/inscripcion/cursado/default.jsp"

    def __init__(self, telegram_token: Optional[str] = None, telegram_chat_id: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0",
            "Accept-Language": "es,es-ES;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,es-AR;q=0.5",
        })
        self.guid: Optional[str] = None
        self.materias_cache: List[Dict[str, Any]] = []
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.server_time_offset: float = 0.0
        self.a4_token: str = ""
        self.a4_timestamp: str = ""
        self.a4_data: str = ""

    def init_cursado(self, usuario: str) -> bool:
        """
        Inicializa la sesión de trámite de cursado en Autogestión 4.
        Carga default.jsp, extrae el idPeticion dinámico y las credenciales A4-Token,
        A4-TimeStamp y A4-Data requeridas por el servidor.
        """
        try:
            # 1. Cargar la página JSP
            jsp_resp = self.session.get(self.REFERER_CURSADO, timeout=10)
            
            # 2. Extraer idPeticion dinámico
            id_peticion = f"0{usuario}F65BBE75EB7C"  # fallback
            match_pet = re.search(r"idPeticion\s*=\s*['\"]([0-9A-Fa-f]+)['\"]", jsp_resp.text)
            if match_pet:
                id_peticion = match_pet.group(1)
                
            # Extraer A4Token, A4TimeStamp y A4Data
            m_tok = re.search(r"var\s+A4Token\s*=\s*['\"]([^'\"]+)['\"]", jsp_resp.text)
            m_ts = re.search(r"var\s+A4TimeStamp\s*=\s*['\"]([^'\"]+)['\"]", jsp_resp.text)
            m_dt = re.search(r"var\s+A4Data\s*=\s*['\"]([^'\"]+)['\"]", jsp_resp.text)
            
            if m_tok: self.a4_token = m_tok.group(1)
            if m_ts: self.a4_timestamp = m_ts.group(1)
            if m_dt: self.a4_data = m_dt.group(1)
            
            ajax_headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://a4.frc.utn.edu.ar",
                "Referer": self.REFERER_CURSADO,
                "A4-Token": self.a4_token,
                "A4-TimeStamp": self.a4_timestamp,
                "A4-Data": self.a4_data,
            }
            
            # 3. POST init
            init_url = f"{self.BASE_URL_A4}/transacciones/inscripcion/cursado/init"
            for _ in range(5):
                try:
                    init_resp = self.session.post(init_url, data={"idPeticion": id_peticion}, headers=ajax_headers, timeout=5)
                    if init_resp.status_code == 200 and init_resp.text.startswith("2"):
                        break
                except Exception:
                    pass
                time.sleep(1)
            
            # 4. POST pendientes
            pendientes_headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://a4.frc.utn.edu.ar",
                "Referer": self.REFERER_CURSADO,
                "A4-Token": self.a4_token,
                "A4-TimeStamp": self.a4_timestamp,
                "A4-Data": self.a4_data,
            }
            self.session.post(f"{self.BASE_URL_A4}/transacciones/inscripcion/cursado/pendientes", headers=pendientes_headers, timeout=5)
            return True
        except Exception:
            return False

    def get_comisiones(self) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """
        Obtiene la oferta académica (materias y comisiones disponibles) y el GUID.
        """
        url = f"{self.BASE_URL_A4}/transacciones/inscripcion/cursado/comisiones"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.REFERER_CURSADO,
            "A4-Token": self.a4_token,
            "A4-TimeStamp": self.a4_timestamp,
            "A4-Data": self.a4_data,
        }
        
        try:
            resp = self.session.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                text = resp.text.strip()
                data = {}
                if text.startswith("Item [") and text.endswith("]"):
                    inner = text[6:-1]
                    m_id = re.search(r"id=([^,\s]+)", inner)
                    m_val = re.search(r"valor=(.*)", inner, re.DOTALL)
                    if m_id:
                        data["id"] = m_id.group(1).strip()
                    if m_val:
                        data["valor"] = m_val.group(1).strip()
                else:
                    try:
                        data = resp.json()
                    except Exception:
                        pass
                        
                self.guid = data.get("id")
                valor_raw = data.get("valor", "")
                
                if valor_raw:
                    try:
                        v_clean = valor_raw.strip()
                        if not v_clean.startswith("["):
                            v_clean = "[" + v_clean + "]"
                        self.materias_cache = json.loads(v_clean)
                        return self.guid, self.materias_cache
                    except Exception:
                        pass
        except Exception:
            pass

        return self.guid, self.materias_cache


    def refresh_guid(self) -> Optional[str]:
        """
        Solicita un GUID nuevo y actualizado antes de enviar la inscripción.
        Maneja errores de red sin romper la ejecución del bot.
        """
        url = f"{self.BASE_URL_A4}/transacciones/guid"
        headers = {"X-Requested-With": "XMLHttpRequest"}
        try:
            resp = self.session.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
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
                
                # Extraer curso exacto (ej. "4K2", "4K3A") combinando año/carrera con el número de comisión y subcomisión opcional
                try:
                    sec_num = str(int(com_code))
                except ValueError:
                    sec_num = ""
                
                m_curso = re.match(r"^([1-5][A-Za-z]+" + re.escape(sec_num) + r"[A-Za-z]?)", rest)
                if m_curso:
                    curso_clean = m_curso.group(1).upper()
                else:
                    curso_clean = rest[:4].strip().upper()
                
                # Extraer bloque de horario: [CURSO][DÍA_1_DIGITO][HHMM_4_DIGITOS][DURACION_MIN_3_DIGITOS]
                day_num = 0
                day_name = ""
                start_time = ""
                end_time = ""
                start_mins = 0
                end_mins = 0
                
                m_sched = re.match(r"^" + re.escape(curso_clean) + r"(\d)(\d{4})(\d{3})", rest)
                if m_sched:
                    d_code = m_sched.group(1)
                    st_hhmm = m_sched.group(2)
                    dur_m = int(m_sched.group(3))
                    
                    days_map = {"1": "Lun", "2": "Mar", "3": "Mié", "4": "Jue", "5": "Vie", "6": "Sáb", "7": "Dom"}
                    day_num = int(d_code)
                    day_name = days_map.get(d_code, f"D{d_code}")
                    
                    sh = int(st_hhmm[:2])
                    sm = int(st_hhmm[2:])
                    start_mins = sh * 60 + sm
                    end_mins = start_mins + dur_m
                    
                    eh = end_mins // 60
                    em = end_mins % 60
                    start_time = f"{sh:02d}:{sm:02d}"
                    end_time = f"{eh:02d}:{em:02d}"

                res.append({
                    "comision_code": com_code,
                    "curso": curso_clean,
                    "rest": rest,
                    "raw": item_clean,
                    "day_num": day_num,
                    "day_name": day_name,
                    "start_time": start_time,
                    "end_time": end_time,
                    "start_mins": start_mins,
                    "end_mins": end_mins
                })
        return res

    def get_horarios_inscriptos(self) -> List[Dict[str, Any]]:
        """
        Retorna la lista de bloques de horario de todas las materias en las que el alumno está inscripto.
        """
        inscriptos_schedules = []
        if not self.materias_cache:
            return inscriptos_schedules
            
        for item in self.materias_cache:
            inscripto_code = item.get("Inscripto")
            if inscripto_code:
                nombre = item.get("Name", "")
                structure = item.get("Structure", "")
                struct_parsed = self.parse_structure(structure)
                
                com_num = inscripto_code[-3:] if len(inscripto_code) >= 3 else ""
                for st in struct_parsed:
                    if st["comision_code"] == com_num and st["start_time"]:
                        inscriptos_schedules.append({
                            "materia": nombre,
                            "curso": st["curso"],
                            "comision_code": st["comision_code"],
                            "day_num": st["day_num"],
                            "day_name": st["day_name"],
                            "start_time": st["start_time"],
                            "end_time": st["end_time"],
                            "start_mins": st["start_mins"],
                            "end_mins": st["end_mins"]
                        })
        return inscriptos_schedules

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
                found_course = False
                
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
                    
                    for curso_target in cursos_target:
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
                                break
                        if found_course:
                            break
                            
                    # Si no hay estructura disponible, usar comisión inferida por defecto
                    if not found_course and not struct_list:
                        for curso_target in cursos_target:
                            m_num = re.search(r"(\d+)(?=[A-Za-z]?$)", curso_target)
                            if m_num:
                                com_code = m_num.group(1).zfill(3)
                                full_code = f"{m_codigo}{com_code}"
                                codes.append(full_code)
                                found_course = True
                                break
                elif mat_code and len(mat_code) == 11:
                    for curso_target in cursos_target:
                        m_num = re.search(r"(\d+)(?=[A-Za-z]?$)", curso_target)
                        if m_num:
                            com_code = m_num.group(1).zfill(3)
                            full_code = f"{mat_code}{com_code}"
                            codes.append(full_code)
                            found_course = True
                            break

                if not found_course:
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
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://a4.frc.utn.edu.ar",
            "Referer": self.REFERER_CURSADO,
            "A4-Token": self.a4_token,
            "A4-TimeStamp": self.a4_timestamp,
            "A4-Data": self.a4_data,
        }
        data = {
            "GUID": self.guid,
            "materia": payload_materia
        }
        
        t_start = time.perf_counter()
        resp = self.session.post(url, data=data, headers=headers)
        t_elapsed = (time.perf_counter() - t_start) * 1000 # ms
        
        # Auto-relogin de seguridad si la sesión de Autogestión caduca tras varias horas
        if "iniciarSesion" in resp.url or "login" in resp.url.lower():
            if self.usuario and self.clave:
                self.login(self.usuario, self.dominio, self.clave)
                self.init_cursado(self.usuario)
                resp = self.session.post(url, data=data, headers=headers)
        
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
        materias_inscriptas = []
        
        # 1. Extraer materias confirmadas del cache de comisiones de la UTN
        if self.materias_cache:
            for item in self.materias_cache:
                inscripto_code = item.get("Inscripto")
                if inscripto_code:
                    nombre = item.get("Name", "")
                    structure = item.get("Structure", "")
                    struct_parsed = self.parse_structure(structure)
                    
                    com_num = inscripto_code[-3:] if len(inscripto_code) >= 3 else ""
                    curso_str = ""
                    for st in struct_parsed:
                        if st["comision_code"] == com_num:
                            curso_str = f" ({st['curso']})"
                            break
                    if not curso_str and struct_parsed:
                        curso_str = f" ({struct_parsed[0]['curso']})"
                        
                    materias_inscriptas.append(f"{nombre}{curso_str}")
                    
        if materias_inscriptas:
            return list(dict.fromkeys(materias_inscriptas))

        # 2. Fallback a endpoint de cursado actual
        url = f"{self.BASE_URL_A4}/cursado/actual/{anio}"
        headers = {"X-Requested-With": "XMLHttpRequest"}
        try:
            resp = self.session.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for item in data:
                        nom = item.get("nombre") or item.get("materia") or str(item)
                        materias_inscriptas.append(nom)
                elif isinstance(data, dict):
                    for k, v in data.items():
                        materias_inscriptas.append(f"{k}: {v}")
        except Exception:
            pass
            
        return list(dict.fromkeys(materias_inscriptas))

