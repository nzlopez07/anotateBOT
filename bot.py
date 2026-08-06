import sys
import json
import time
import argparse
import re
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional
from client import UTNInscripcionClient

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Renderizador de Reloj Digital ASCII (100% compatible con cualquier terminal Windows/Linux)
ASCII_DIGITS = {
    '0': [" ### ", "#   #", "#   #", "#   #", " ### "],
    '1': ["  #  ", " ##  ", "  #  ", "  #  ", " ### "],
    '2': [" ### ", "    #", " ### ", "#    ", "#####"],
    '3': [" ### ", "    #", " ### ", "    #", " ### "],
    '4': ["#   #", "#   #", "#####", "    #", "    #"],
    '5': ["#####", "#    ", "#### ", "    #", "#### "],
    '6': [" ### ", "#    ", "#### ", "#   #", " ### "],
    '7': ["#####", "    #", "   # ", "  #  ", "  #  "],
    '8': [" ### ", "#   #", " ### ", "#   #", " ### "],
    '9': [" ### ", "#   #", " ####", "    #", " ### "],
    ':': ["   ", " o ", "   ", " o ", "   "]
}

def render_ascii_clock(time_str: str) -> str:
    lines = ["", "", "", "", ""]
    for char in time_str:
        digit_lines = ASCII_DIGITS.get(char, ["     "] * 5)
        for i in range(5):
            lines[i] += digit_lines[i] + " "
    return "\n".join(lines)


def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[❌] Archivo {config_path} no encontrado.")
        sys.exit(1)
    except Exception as e:
        print(f"[❌] Error al leer {config_path}: {e}")
        sys.exit(1)

def print_header():
    print("=" * 65)
    print("        anotateBOT - UTN FRC Inscripcion por API HTTP")
    print("=" * 65)

def parse_server_breakdown(client: UTNInscripcionClient, raw_response: str, config: Dict[str, Any]) -> List[str]:
    """
    Analiza la respuesta detallada del servidor de la UTN y determina
    materia por materia cuáles consiguieron cupo/posición y cuáles no.
    """
    lines = []
    deseadas = config.get("comisiones_deseadas", [])
    
    for sel in deseadas:
        mat_name = sel.get("materia", "Materia")
        curso = sel.get("curso", "")
        if isinstance(curso, list):
            curso = "/".join(curso)
            
        code_resolved = client.resolve_materia_payload([sel])
        
        # Verificar estado oficial directo en el servidor de la UTN
        verif = client.verificar_posicion_materia(code_resolved) if code_resolved else {}
        val_str = str(verif.get("value", ""))
        
        if "Inscripcion Definitiva" in val_str or "1|" in val_str or "ACEPTADA" in val_str.upper():
            lines.append(f"[✔] {mat_name} ({curso}): INSCRIPCION DEFINITIVA CONFIRMADA (Codigo: {code_resolved})")
        elif "SIN LUGAR" in raw_response.upper() or "SIN CUPO" in raw_response.upper() or "RESPUESTA\":\"0" in raw_response.replace(" ", ""):
            lines.append(f"[❌] {mat_name} ({curso}): SIN CUPO DISPONIBLE (Reintentando...)")
        elif code_resolved:
            lines.append(f"[❌] {mat_name} ({curso}): SIN CUPO O PENDIENTE DE LIBERACION (Codigo: {code_resolved})")
        else:
            lines.append(f"[❌] {mat_name} ({curso}): NO FIGURA EN LA OFERTA VIVA")
            
    return lines



def cmd_list(client: UTNInscripcionClient, config: Dict[str, Any], watch: bool = False):
    print("\n[+] Autenticando en UTN FRC...")
    if not client.login(config["usuario"], config.get("dominio", "sistemas"), config["clave"]):
        print("[❌] Error de autenticacion. Verifique su legajo y clave.")
        return
    print("[✔] Login exitoso.")
    
    client.init_cursado(config["usuario"])
    
    previous_snapshot = ""
    cycle = 0
    
    while True:
        cycle += 1
        guid, materias = client.get_comisiones()
        
        if watch:
            os.system('cls' if os.name == 'nt' else 'clear')
            print_header()
            print(f" [ {datetime.now().strftime('%H:%M:%S')} ] | MODO MONITOR CONTINUO (Ciclo #{cycle})")
            print("=" * 65)
        
        if not materias:
            print("[!] La consulta en vivo aun no fue abierta por la facultad.")
        else:
            print(f"[✔] Oferta cargada correctamente (GUID: {guid})")
            print("=" * 65)
            print(f"{'CODIGO':<12} | {'MATERIA':<35} | {'CURSOS DISPONIBLES'}")
            print("-" * 65)
            
            current_snapshot_lines = []
            for m in materias:
                codigo = m.get("CODIGO", "N/A")
                nombre = m.get("Name", "N/A")
                structure = m.get("Structure", "")
                struct_parsed = client.parse_structure(structure)
                
                cursos_list = []
                for st in struct_parsed:
                    c_entry = f"{st['curso']} (Com:{st['comision_code']})"
                    if c_entry not in cursos_list:
                        cursos_list.append(c_entry)
                        
                cursos_str = ", ".join(cursos_list)
                current_snapshot_lines.append(f"{codigo} - {nombre}: {cursos_str}")
                
                if len(nombre) > 34:
                    nombre_disp = nombre[:31] + "..."
                else:
                    nombre_disp = nombre
                print(f"{codigo:<12} | {nombre_disp:<35} | {cursos_str}")
                
            print("=" * 65)
            
            # Alerta a Telegram si cambia la oferta mientras está en modo watch
            current_snapshot = "\n".join(current_snapshot_lines)
            if watch and previous_snapshot and current_snapshot != previous_snapshot:
                if client.telegram_token:
                    # Calcular la diferencia exacta entre snapshots
                    prev_set = set(previous_snapshot.split("\n"))
                    curr_set = set(current_snapshot.split("\n"))
                    diff_added = curr_set - prev_set
                    diff_removed = prev_set - curr_set
                    
                    diff_text = ""
                    if diff_added:
                        diff_text += "\n➕ *Nuevos/Modificados:*\n" + "\n".join([f"• {x}" for x in diff_added])
                    if diff_removed:
                        diff_text += "\n➖ *Retirados:*\n" + "\n".join([f"• {x}" for x in diff_removed])
                        
                    client.send_telegram(f"🔔 *anotateBOT: ¡CAMBIO DETECTADO EN LA OFERTA VIVA!*{diff_text}")
            previous_snapshot = current_snapshot

        if not watch:
            break
            
        time.sleep(5)

def cmd_schedule(client: UTNInscripcionClient, config: Dict[str, Any], check_target: Optional[str] = None, watch: bool = False):
    print("\n[+] Autenticando en UTN FRC...")
    if not client.login(config["usuario"], config.get("dominio", "sistemas"), config["clave"]):
        print("[❌] Error de autenticacion.")
        return
    print("[✔] Login exitoso.")
    
    client.init_cursado(config["usuario"])
    
    cycle = 0
    while True:
        cycle += 1
        client.get_comisiones()
        
        if watch:
            os.system('cls' if os.name == 'nt' else 'clear')
            print_header()
            print(f" [ {datetime.now().strftime('%H:%M:%S')} ] | MODO MONITOR CONTINUO DE HORARIOS (Ciclo #{cycle})")
            print("=" * 70)
    
        inscriptos = client.get_horarios_inscriptos()
        if not inscriptos:
            print("[!] No se encontraron materias inscriptas o la oferta no está cargada.")
            if not watch:
                break
            time.sleep(5)
            continue

        # Organizar bloques por día
        days_order = [(1, "LUNES"), (2, "MARTES"), (3, "MIÉRCOLES"), (4, "JUEVES"), (5, "VIERNES"), (6, "SÁBADO")]
        
        print("\n" + "=" * 70)
        print("📅 AGENDA SEMANAL OFICIAL (MATERIA INCRIPTAS)")
        print("=" * 70)
        
        for d_num, d_name in days_order:
            day_blocks = [b for b in inscriptos if b["day_num"] == d_num]
            print(f"\n📌 {d_name}:")
            if not day_blocks:
                print("   (Libre)")
            else:
                day_blocks.sort(key=lambda x: x["start_mins"])
                for b in day_blocks:
                    mat_short = b["materia"][:35]
                    print(f"   • {b['start_time']} - {b['end_time']} | {mat_short} ({b['curso']})")
        
        print("\n" + "=" * 70)
        print("📚 OFERTA COMPLETA DE HORARIOS Y COMISIONES DISPONIBLES EN VIVO")
        print("=" * 70)
        
        for m in client.materias_cache:
            nombre = m.get("Name", "")
            codigo = m.get("CODIGO", "")
            structure = m.get("Structure", "")
            struct_parsed = client.parse_structure(structure)
            
            if not struct_parsed:
                continue
                
            print(f"\n📖 {nombre} (Codigo: {codigo}):")
            
            # Agrupar por curso/comision
            by_course = {}
            for st in struct_parsed:
                key = (st["curso"], st["comision_code"])
                by_course.setdefault(key, []).append(st)
                
            for (c_name, c_code), blocks in by_course.items():
                times_str = []
                for b in blocks:
                    if b["start_time"]:
                        times_str.append(f"{b['day_name']} {b['start_time']}-{b['end_time']}")
                sched_display = " | ".join(times_str) if times_str else "(Sin horario decodificado)"
                print(f"   • Curso {c_name} (Comisión {c_code}): {sched_display}")
                
        print("\n" + "=" * 70)
        
        # Si el usuario solicitó verificar la compatibilidad de un curso candidato
        if check_target:
            print(f"\n🔍 EVALUANDO SOLAPAMIENTO DE HORARIOS PARA: '{check_target}'")
            print("-" * 70)
            
            candidates = []
            for m in client.materias_cache:
                m_nombre = m.get("Name", "")
                m_code = m.get("CODIGO", "")
                structure = m.get("Structure", "")
                struct_parsed = client.parse_structure(structure)
                
                for st in struct_parsed:
                    if (check_target.upper() in st["curso"].upper() or check_target.lower() in m_nombre.lower() or check_target == m_code) and st["start_time"]:
                        candidates.append({
                            "materia": m_nombre,
                            "curso": st["curso"],
                            "comision_code": st["comision_code"],
                            "day_num": st["day_num"],
                            "day_name": st["day_name"],
                            "start_time": st["start_time"],
                            "end_time": st["end_time"],
                            "start_mins": st["start_mins"],
                            "end_mins": st["end_mins"]
                        })
                        
            if not candidates:
                print(f"[!] No se encontraron horarios para '{check_target}' en la oferta viva.")
            else:
                # Agrupar candidatos por materia y curso
                grouped = {}
                for c in candidates:
                    key = (c["materia"], c["curso"], c["comision_code"])
                    grouped.setdefault(key, []).append(c)
                    
                for (m_nom, c_cur, c_code), blocks in grouped.items():
                    print(f"\n👉 Candidata: {m_nom} | Curso: {c_cur} (Comision {c_code})")
                    has_conflict = False
                    
                    for cb in blocks:
                        print(f"   Horario: {cb['day_name']} {cb['start_time']} - {cb['end_time']}")
                        
                        # Buscar choques con materias inscriptas
                        for ib in inscriptos:
                            if ib["day_num"] == cb["day_num"]:
                                # Verificar solapamiento de rangos [start, end]
                                if max(cb["start_mins"], ib["start_mins"]) < min(cb["end_mins"], ib["end_mins"]):
                                    has_conflict = True
                                    print(f"   ⚠️  [CHOQUE/SOLAPAMIENTO] Con: {ib['materia']} ({ib['curso']}) [{ib['start_time']} - {ib['end_time']}]")
                                    
                    if not has_conflict:
                        print("   ✅ ¡HORARIO COMPATIBLE! No tiene solapamientos con tus materias actuales.")
                print("\n" + "=" * 70)

        if not watch:
            break
        time.sleep(5)

def cmd_dry_run(client: UTNInscripcionClient, config: Dict[str, Any]):
    print("\n[+] MODO DRY-RUN (Simulacion)")
    print("[+] Autenticando...")
    if not client.login(config["usuario"], config.get("dominio", "sistemas"), config["clave"]):
        print("[❌] Error de autenticacion.")
        return
    print("[✔] Login exitoso.")
    
    client.init_cursado(config["usuario"])
    guid, materias = client.get_comisiones()
    
    deseadas = config.get("comisiones_deseadas", [])
    directas = config.get("codigos_directos", [])
    payload = client.resolve_materia_payload(list(deseadas) + list(directas))
    
    print("\n" + "=" * 65)
    print("RESUMEN DE SIMULACION:")
    print(f"  • Payload a enviar: {payload if payload else '(Ninguno resuelto)'}")
    print(f"  • GUID listo: {guid}")
    print(f"  • Telegram: {'CONECTADO' if client.telegram_token else 'NO CONFIGURADO'}")
    print("=" * 65)
    
    if client.telegram_token:
        client.send_telegram("anotateBOT: Prueba Dry-Run realizada con exito.")

def cmd_sniper(client: UTNInscripcionClient, config: Dict[str, Any], target_time_str: str = None):
    now = datetime.now()
    
    # Si no se pasa la flag --time (o se omite), dispara la inscripcion inmediatamente
    if not target_time_str:
        print("\n[+] MODO SNIPER INMEDIATO (Sin temporizador)")
        print("🚀 Disparando inscripcion en este instante para todas tus materias...\n")
        target_dt = now
    else:
        print(f"\n[+] MODO SNIPER TEMPORIZADO (Hora Objetivo: {target_time_str})")
        target_time = datetime.strptime(target_time_str, "%H:%M:%S").time()
        target_dt = datetime.combine(now.date(), target_time)
        
        if target_dt < now:
            diff_seconds = (now - target_dt).total_seconds()
            if diff_seconds < 7200:
                print(f"\n[!] La hora objetivo ({target_time_str}) ya paso hoy (hace {int(diff_seconds/60)} min).")
                print("[+] Disparando inscripcion DIRECTA E INMEDIATA en este instante...\n")
                target_dt = now
            else:
                target_dt += timedelta(days=1)



    print("[+] Autenticando en UTN FRC...")
    if not client.login(config["usuario"], config.get("dominio", "sistemas"), config["clave"]):
        print("[❌] Error de autenticacion.")
        return
    print("[✔] Login exitoso.")
    
    client.init_cursado(config["usuario"])
    guid, materias = client.get_comisiones()
    
    deseadas = config.get("comisiones_deseadas", [])
    directas = config.get("codigos_directos", [])
    payload = client.resolve_materia_payload(list(deseadas) + list(directas))
    
    if client.telegram_token:
        obj_text = target_time_str if target_time_str else "Inmediato (Modo Continuo)"
        client.send_telegram(f"🟢 anotateBOT Iniciado | Legajo: {config['usuario']} | Modo: {obj_text}")


    print("\n" + "=" * 65)
    print("ESTADO DEL MONITOR:")
    print(f"  • Usuario: {config['usuario']}")
    print(f"  • Hora Objetivo: {target_dt.strftime('%H:%M:%S')}")
    print(f"  • Payload Inicial: {payload if payload else '(Pendiente de apertura)'}")
    print(f"  • Telegram: {'Activo' if client.telegram_token else 'Inactivo'}")
    print("=" * 65)
    
    notified_5min = False
    notified_1min = False
    
    # Bucle con Reloj Digital ASCII Gigante en pantalla
    while True:
        current = datetime.now()
        seconds_left = (target_dt - current).total_seconds()
        
        if seconds_left <= 10:
            break
            
        current_time_str = current.strftime('%H:%M:%S')
        target_time_display = target_dt.strftime('%H:%M:%S')
        sec_display = int(seconds_left)
        
        # Limpiar consola e imprimir Reloj ASCII Gigante
        os.system('cls' if os.name == 'nt' else 'clear')
        print_header()
        print(render_ascii_clock(current_time_str))
        print("=" * 65)
        print(f"  OBJETIVO: {target_time_display} | FALTAN: {sec_display} segundos | SESION ACTIVA")
        print("=" * 65)
        
        if 295 <= seconds_left <= 300 and not notified_5min:
            client.send_telegram("anotateBOT: Quedan 5 minutos para el inicio de inscripcion.")
            notified_5min = True
            
        if 55 <= seconds_left <= 60 and not notified_1min:
            client.send_telegram("anotateBOT: Queda 1 MINUTO para el disparo.")
            notified_1min = True

        if int(seconds_left) % 45 == 0 and seconds_left > 15:
            guid, materias = client.get_comisiones()
            payload_updated = client.resolve_materia_payload(list(deseadas) + list(directas))
            if payload_updated and payload_updated != payload:
                payload = payload_updated
                client.send_telegram(f"anotateBOT: Nueva oferta viva detectada -> {payload}")
                
        time.sleep(1.0)

    guid, materias = client.get_comisiones()
    payload_final = client.resolve_materia_payload(list(deseadas) + list(directas))
    if payload_final:
        payload = payload_final
        
    # Espera activa sub-milisegundo
    while datetime.now() < target_dt:
        pass

        
    shot_count = 0
    last_heartbeat = datetime.now()
    
    while True:
        shot_count += 1
        shot_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        
        # 1. Enviar disparo de inscripción limpio
        client.refresh_guid()
        res_first = client.enviar_inscripcion(payload)
        
        # 2. Consultar comprobante oficial y materias inscriptas en la UTN
        inscriptas_oficiales = client.verificar_inscripciones_actuales()
        
        # 3. Identificar materias pendientes
        missing_sel = []
        for sel in deseadas:
            code_res = client.resolve_materia_payload([sel])
            verif = client.verificar_posicion_materia(code_res) if code_res else {}
            val_str = str(verif.get("value", ""))
            
            if not ("Inscripcion Definitiva" in val_str or "1|" in val_str or "ACEPTADA" in val_str.upper()):
                missing_sel.append(sel)
                
        # 4. Imprimir resumen visual en pantalla limpia
        os.system('cls' if os.name == 'nt' else 'clear')
        print_header()
        print(f" [ {datetime.now().strftime('%H:%M:%S')} ] | RAFAGA #{shot_count} | MONITOREO ACTIVO")
        print("=" * 65)
        print("MATERIAS CONFIRMADAS EN TU AUTOGESTION (UTN FRC):")
        if inscriptas_oficiales:
            for ins in inscriptas_oficiales:
                print(f"  [✔] {ins}")
        else:
            print("  (Ninguna materia inscripta o confirmada aun)")
            
        print("\nMATERIAS PENDIENTES DE CUPO (Buscando vacante en vivo):")
        if missing_sel:
            for m in missing_sel:
                m_nombre = m.get("materia", "")
                m_curso = str(m.get("curso", ""))
                print(f"  [❌] {m_nombre} ({m_curso}) -> SIN CUPO (Reintentando en 5s...)")
        else:
            print("  (Ninguna pendiente - 100% Completado)")
            
        print("=" * 65)


        # Si NO faltan materias (todas conseguidas), finalizar ciclo con gran alerta a Telegram
        if not missing_sel:
            print("\n[✔] ¡TODAS LAS MATERIAS HAN SIDO INSCRIPTAS DEFINITIVAMENTE CON EXITO!")
            if client.telegram_token:
                client.send_telegram("🎉 *¡INSCRIPCIÓN DEFINITIVA CONSEGUIDA EN DEVOPS (4K4)!*\nPuedes ingresar a Autogestión a descargar tu comprobante final.")
            break
            
        # Alerta de Heartbeat cada 30 minutos a Telegram (1800 segundos)
        now_dt = datetime.now()
        if (now_dt - last_heartbeat).total_seconds() >= 1800:
            if client.telegram_token:
                missing_names = ", ".join([m.get("materia", "") + " (" + str(m.get("curso", "")) + ")" for m in missing_sel])
                client.send_telegram(f"🟢 anotateBOT Activo | Rafaga #{shot_count} | Buscando cupo para: {missing_names}")
            last_heartbeat = now_dt

        # Reintentar en 5 segundos
        missing_payload = client.resolve_materia_payload(missing_sel)
        if missing_payload:
            payload = missing_payload
            time.sleep(5)
        else:
            time.sleep(5)


    # Verificación del comprobante oficial final en el servidor de la UTN
    print("\n[+] VERIFICANDO COMPROBANTE OFICIAL FINAL EN UTN...")
    time.sleep(1)
    inscriptas = client.verificar_inscripciones_actuales()
    if inscriptas:
        print("\n[✔] COMPROBANTE OFICIAL CONFIRMADO EN SERVIDOR DE LA UTN:")
        for ins in inscriptas:
            print(f"  • {ins}")




def cmd_demo(client: UTNInscripcionClient, config: Dict[str, Any]):

    print("\n[+] MODO DEMO - SIMULACION INTERACTIVA EN TIEMPO REAL")
    print("[+] Inicializando simulacion de los ultimos 10 segundos antes de las 17:00:00...\n")
    time.sleep(2)
    
    # 1. Simulación de los últimos 10 segundos con Reloj Digital ASCII
    target_dt = datetime.now() + timedelta(seconds=10)
    
    while True:
        current = datetime.now()
        seconds_left = (target_dt - current).total_seconds()
        
        if seconds_left <= 0:
            break
            
        current_time_str = current.strftime('%H:%M:%S')
        sec_display = max(0, int(seconds_left))
        
        os.system('cls' if os.name == 'nt' else 'clear')
        print_header()
        print(render_ascii_clock(current_time_str))
        print("=" * 65)
        print(f"  OBJETIVO: 17:00:00 | FALTAN: {sec_display:>2} segundos | SESION ACTIVA")
        print("=" * 65)
        time.sleep(0.5)
        
    os.system('cls' if os.name == 'nt' else 'clear')
    print_header()
    shot_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[+] Disparando rafaga a las {shot_time}...")
    if client.telegram_token:
        client.send_telegram(f"anotateBOT Demo: Disparando inscripcion a las {shot_time}")
    
    time.sleep(0.3)
    print("  [Disparo 1] 42.1 ms | Status 200")
    print("  [Disparo 2] 45.8 ms | Status 200")
    print("  [Disparo 3] 48.3 ms | Status 200")
    
    print("\n[✔] Respuesta inicial del servidor (42.1 ms)")
    print("\nDESGLOSE INICIAL POR MATERIA (2 Conseguidas, 2 Pendientes):")
    print("  [✔] Ingenieria y Calidad de Software (4K2): PROCESADA EN COLA / CONSEGUIDA")
    print("  [✔] Seguridad en el Desarrollo de Software (5K4): PROCESADA EN COLA / CONSEGUIDA")
    print("  [❌] Tecnologias para la Automatizacion (4K2): SIN CUPO / PENDIENTE")
    print("  [❌] DevOps (4K4): SIN CUPO / PENDIENTE")
    
    if client.telegram_token:
        client.send_telegram("anotateBOT Demo: Respuesta Inicial -> 2 materias conseguidas (ICW, SDS), 2 pendientes (TA, DO).")
        
    time.sleep(3)
    print("\n[+] REINTENTO SELECTIVO ACTIVADO (Solo materias pendientes: TA, DO)")
    print("    (Las materias conseguidas ICW y SDS estan 100% seguras y no se modifican)")
    
    if client.telegram_token:
        client.send_telegram("anotateBOT Demo: Reintentando solo materias pendientes (TA, DO)...")
        
    time.sleep(3)
    print("  [Reintento 1] 44.2 ms | [✔] Tecnologias para la Automatizacion (4K2): CONSEGUIDA EN REINTENTO")
    print("\nDESGLOSE ACTUALIZADO (3 Conseguidas, 1 Pendiente):")
    print("  [✔] Ingenieria y Calidad de Software (4K2): CONSEGUIDA")
    print("  [✔] Seguridad en el Desarrollo de Software (5K4): CONSEGUIDA")
    print("  [✔] Tecnologias para la Automatizacion (4K2): CONSEGUIDA EN REINTENTO")
    print("  [❌] DevOps (4K4): SIN CUPO / PENDIENTE (Falta 1)")
    
    if client.telegram_token:
        client.send_telegram("anotateBOT Demo: Reintento 1 -> TA conseguida! Queda solo DevOps.")
        
    time.sleep(3)
    print("  [Reintento 2] 41.8 ms | [✔] DevOps (4K4): CONSEGUIDA EN REINTENTO")
    
    print("\n" + "=" * 65)
    print("[✔] ESTADO FINAL: 🎉 ¡100% DE LAS MATERIAS INSCRIPTAS CON EXITO!")
    print("  [✔] Ingenieria y Calidad de Software (4K2): CONSEGUIDA")
    print("  [✔] Seguridad en el Desarrollo de Software (5K4): CONSEGUIDA")
    print("  [✔] Tecnologias para la Automatizacion (4K2): CONSEGUIDA")
    print("  [✔] DevOps (4K4): CONSEGUIDA")
    print("=" * 65)
    
    if client.telegram_token:
        client.send_telegram("anotateBOT Demo: 🎉 ¡100% DE TUS MATERIAS INSCRIPTAS CON EXITO!\n\n✔ ICW (4K2)\n✔ SDS (5K4)\n✔ TA (4K2)\n✔ DO (4K4)")



def main():
    print_header()
    parser = argparse.ArgumentParser(description="anotateBOT - UTN FRC API HTTP")
    parser.add_argument("modo", choices=["list", "schedule", "dry-run", "sniper", "demo"], 
                        help="Modo de ejecucion: list, schedule, dry-run, sniper, demo")
    parser.add_argument("--watch", "-w", action="store_true", help="Monitoreo continuo en vivo del listado de materias y comisiones.")
    parser.add_argument("--check", "-c", type=str, default=None, help="Materia o comision a evaluar choques de horario (ej: --check 4K1)")
    parser.add_argument("--time", type=str, default=None, help="Hora objetivo para modo sniper (HH:MM:SS). Si se omite, dispara inmediatamente.")
    parser.add_argument("--config", type=str, default="config.json", help="Ruta al archivo config.json")
    
    args = parser.parse_args()
    config = load_config(args.config)
    client = UTNInscripcionClient()
    
    telegram_token = config.get("telegram_token", "")
    telegram_chat_id = config.get("telegram_chat_id", "")
    if telegram_token and telegram_chat_id:
        client.setup_telegram(telegram_token, telegram_chat_id)
        
    if args.modo == "list":
        cmd_list(client, config, watch=args.watch)
    elif args.modo == "schedule":
        cmd_schedule(client, config, check_target=args.check, watch=args.watch)
    elif args.modo == "dry-run":
        cmd_dry_run(client, config)
    elif args.modo == "sniper":
        cmd_sniper(client, config, args.time)
    elif args.modo == "demo":
        cmd_demo(client, config)


if __name__ == "__main__":
    main()

