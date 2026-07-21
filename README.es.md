# LumaBLE

Aplicación de escritorio para Windows para controlar controladores BLE RGB de tiras LED.

LumaBLE escanea controladores Bluetooth compatibles cercanos, se conecta al dispositivo, cambia el
color RGB, el brillo y el encendido, aplica efectos integrados, ajusta la velocidad de los efectos y
guarda perfiles de iluminación reutilizables. También incluye sincronización con pantalla,
controles en la bandeja, horarios locales, diagnósticos, temas y activación Pro para funciones
avanzadas.

Autor: `dollza`

Versión: `0.3.4 beta`

Descarga la última build para Windows desde la página de
[Releases](https://github.com/DanKo12345/lumable/releases).

Si encuentras un error o tu controlador no funciona, abre un
[Issue](https://github.com/DanKo12345/lumable/issues).

Otros idiomas:

- [English](README.md)
- [Русский](README.ru.md)
- [中文](README.zh.md)

## Funciones principales

- Deslizadores RGB, selector HEX/HSV, brillo y control de encendido.
- Efectos BLE integrados con control de velocidad cuando el protocolo lo permite.
- Perfiles de iluminación reutilizables y modos rápidos.
- Sincronización con pantalla / Ambient para ajustar la tira al color promedio de la pantalla.
- Horarios locales mientras la aplicación está abierta o en la bandeja.
- Protección de instancia única: una segunda apertura trae la ventana existente al frente.
- Exportación de diagnósticos para controladores no compatibles y problemas BLE.
- Idiomas de interfaz: inglés, ruso, español y chino, con detección automática en el primer inicio.

## Controladores compatibles

- Controladores compatibles con BLEDOM / ELK-BLEDOM.
- Controladores BLE Magic Home / MagicLight.
- Controladores BLE BanlanX SP61x / SP62x.
- Controladores BLE compatibles con Triones / Happy Lighting.

## Instalación en Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Herramientas para tests y builds de release:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Ejecutar

```powershell
.\run_app.bat
```

## Tests

```powershell
.\.venv311\Scripts\python.exe -m pytest
```

```powershell
.\.venv311\Scripts\python.exe -m ruff check .
```

## Datos de la aplicación

Los datos de la aplicación se guardan en la carpeta estándar de datos de usuario mediante
`platformdirs`. En Windows normalmente es:

```text
%APPDATA%\LumaBLE
```

Las traducciones personalizadas se pueden añadir como archivos JSON en:

```text
%APPDATA%\LumaBLE\i18n
```

La carpeta local `data/` solo se usa como fuente legacy para migrar perfiles/configuración antiguos
de desarrollo. No debe incluirse en commits ni en archivos públicos.

## Reportar problemas

Cuando reportes un bug o un controlador no compatible, incluye:

- Versión de Windows.
- Versión de LumaBLE.
- Nombre del controlador mostrado en la aplicación.
- Qué intentaste hacer.
- Qué ocurrió en su lugar.
- Informe de diagnóstico, si es posible.

Para exportar diagnósticos:

1. Abre LumaBLE.
2. Abre Diagnóstico del dispositivo.
3. Pulsa Copiar diagnóstico o Exportar diagnóstico.
4. Pega el informe en el issue de GitHub o adjunta el archivo `.txt` exportado.
