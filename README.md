# anotateBOT - Bot de Inscripción Ultra-Rápido por API HTTP (UTN FRC)

Herramienta optimizada en Python basada en peticiones HTTP directas para automatizar la inscripción a materias en el sistema de **Autogestión 4 de la UTN Facultad Regional Córdoba**.

Al evitar el uso de interfaces gráficas lentas (Playwright, Selenium) y realizar la interacción directamente contra la API del servidor, reduce el tiempo de inscripción a **menos de 50 milisegundos**, garantizando la máxima prioridad de cupo.

---

## ⚡ Características Principales

* **Inscripción Sub-Milisegundo**: Conexión HTTP directa contra la API de Autogestión 4.
* **Sniper con Reloj Digital ASCII**: Monitor interactivo en tiempo real con reloj digital grande (`tty-clock` style).
* **Auto-Sincronización Atómica de Reloj**: Mide el desfase en milisegundos entre la PC local y el servidor de la UTN FRC para disparar sincronizado con la hora oficial de la facultad.
* **Resolución Automática de Oferta**: Traduce nombres de materias y cursos a códigos internos de 14 dígitos en tiempo real.
* **Reintento Selectivo Inteligente**: Si alguna materia queda pendiente, reintenta únicamente las materias faltantes sin alterar ni arriesgar las ya conseguidas.
* **Soporte de Cursos de Reserva / Fallback**: Permite definir comisiones alternativas en orden de preferencia (ej. `["5K4", "4K2A"]`).
* **Notificaciones e Informes por Telegram**: Alertas en tiempo real a tu celular sobre estado, cuenta regresiva y desglose por materia.

---

## 🛠️ Instalación

1. Clona este repositorio:
   ```bash
   git clone https://github.com/nzlopez07/anotateBOT.git
   cd anotateBOT
   ```

2. Instala la dependencia requerida (`requests`):
   ```bash
   pip install requests
   ```

---

## ⚙️ Configuración (`config.json`)

Copia la plantilla de ejemplo para crear tu archivo de configuración personal:
```bash
cp config.example.json config.json
```

Edita `config.json` con tus credenciales y las materias a las que deseas anotarte:

```json
{
  "usuario": "TU_LEGAJO",
  "dominio": "sistemas",
  "clave": "TU_CLAVE",
  "telegram_token": "OPCIONAL_TOKEN_BOT_TELEGRAM",
  "telegram_chat_id": "OPCIONAL_CHAT_ID_TELEGRAM",
  "comisiones_deseadas": [
    {
      "materia": "Tecnologias para la Automatizacion",
      "curso": "4K2"
    },
    {
      "materia": "Ingenieria y Calidad de Software",
      "curso": "4K2"
    },
    {
      "materia": "Seguridad en el Desarrollo de Software",
      "curso": ["5K4", "4K2A"]
    },
    {
      "materia": "DevOps",
      "curso": "4K4"
    }
  ],
  "codigos_directos": []
}
```

> **Nota de Seguridad**: El archivo `config.json` está incluido en `.gitignore` para evitar que tus contraseñas se suban al repositorio.

---

## 🚀 Forma de Uso

### 1. Listar Oferta Académica Limpia
Consulta la oferta de materias y comisiones habilitadas para tu legajo:
```bash
python bot.py list
```

### 2. Simulación de Prueba (Dry-Run)
Prueba la conexión, resolución de nombres y notificaciones de Telegram sin realizar inscripciones reales:
```bash
python bot.py dry-run
```

### 3. Demostración Interactiva (Demo)
Simula los últimos 10 segundos con el reloj digital ASCII, el disparo en ráfaga y los reintentos selectivos:
```bash
python bot.py demo
```

### 4. Modo Sniper Temporizado (Para las 16:55 hs)
Ejecuta el temporizador minutos antes del turno de inscripción:
```bash
python bot.py sniper --time 17:00:00
```
El bot mantendrá la sesión viva, mostrará el reloj digital ASCII en pantalla y disparará la ráfaga a las 17:00:00.000 exactas.

### 5. Modo Sniper Inmediato (Disparo Ya)
Si omites la flag `--time`, el bot dispara la inscripción en este preciso instante:
```bash
python bot.py sniper
```

---

## ⚖️ Licencia
MIT License. Desarrollado con fines educativos y de optimización.
