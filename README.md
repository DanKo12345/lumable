# BLEDOM Glass Controller

Красивое Windows-приложение для управления BLE RGB-лентой на контроллере BLEDOM.

## Возможности

- поиск BLE-устройств и подключение к `BLEDOM`
- смена RGB-цвета
- регулировка яркости
- включение и выключение питания
- эффекты и скорость эффектов
- сохранение, загрузка и удаление конфигов
- сохранение последнего состояния приложения

## Запуск

```powershell
.\.venv\Scripts\python.exe main.py
```

## Зависимости

Если окружение ещё не создано:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```
