from __future__ import annotations

import json
import re
from typing import Any


L10N_PREFIX = "__L10N__"
L10N_SUFFIX = "__END__"

LANGUAGE_ORDER: tuple[str, ...] = ("ru", "en", "zh")

LANGUAGE_LABELS: dict[str, str] = {
    "ru": "Русский",
    "en": "English",
    "zh": "中文",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        "hero.title": "RGB контроллер",
        "language.label": "Язык интерфейса",
        "hero.subtitle": "Управление подсветкой через Bluetooth",
        "device.title": "Устройство",
        "device.subtitle": "Поиск и подключение поддерживаемых BLE-контроллеров.",
        "device.find": "Найти контроллер",
        "device.connect": "Подключить",
        "device.disconnect": "Отключить",
        "device.show_logs": "Показать логи",
        "device.hide_logs": "Скрыть логи",
        "device.status.not_connected": "Не подключено",
        "device.status.connected": "Подключено",
        "device.status.scanning": "Идёт поиск",
        "device.status.not_found": "Контроллер не найден",
        "device.status.found_one": "Найден: {name}",
        "device.status.found_many": "Найдено контроллеров: {count}",
        "device.choice.scan_placeholder": "Поиск контроллеров...",
        "device.choice.not_found": "Поддерживаемые контроллеры не найдены",
        "color.title": "Цвет",
        "color.subtitle": "Ползунки меняют превью. Нажмите «Применить», чтобы отправить цвет на устройство.",
        "color.pick": "Выбрать цвет",
        "color.apply": "Применить",
        "power.on": "Включить",
        "power.off": "Выключить",
        "effects.title": "Эффекты",
        "effects.subtitle": "Статичный цвет — возврат к обычному ручному управлению RGB.",
        "effects.speed": "Скорость",
        "configs.title": "Конфиги",
        "configs.subtitle": "Сохраняйте любимые сцены и быстро загружайте их обратно.",
        "configs.placeholder": "Например: Blue Night",
        "configs.save": "Сохранить",
        "configs.load": "Загрузить",
        "configs.delete": "Удалить",
        "configs.reset": "Сбросить",
        "logs.title": "Логи сессии",
        "logs.subtitle": "Технические события Bluetooth.",
        "theme.dark": "Тёмная тема",
        "theme.light": "Светлая тема",
        "theme.auto": "Авто-тема",
        "dialog.title": "RGB контроллер",
        "dialog.ok": "OK",
        "dialog.pick_color": "Выберите RGB-цвет",
        "preview.rgb": "RGB {r}, {g}, {b}  |  {brightness_label} {brightness}%",
        "error.wait_scan": "Дождитесь окончания поиска устройств.",
        "error.find_first": "Сначала нажмите «Найти контроллер».",
        "error.enter_profile_name": "Введите имя конфига.",
        "error.select_profile_first": "Сначала выберите конфиг.",
        "error.connect_strip_first": "Сначала подключитесь к LED-ленте.",
        "error.connect_strip_to_apply_profile": "Сначала подключитесь к LED-ленте, чтобы применить конфиг.",
        "status.ready_find": "Готово. Нажмите «Найти контроллер», чтобы найти поддерживаемые устройства.",
        "status.profile_loaded_local": "Конфиг загружен в интерфейс. Подключите LED-ленту, чтобы применить его.",
        "status.static_color_mode": "Режим статичного цвета.",
        "status.defaults_restored": "Стандартные конфиги восстановлены.",
        "status.config_saved": "Конфиг «{name}» сохранён.",
        "status.config_loaded": "Конфиг «{name}» загружен.",
        "status.config_deleted": "Конфиг «{name}» удалён.",
        "status.autofound_connecting": "Найден: {name} ({address}). Автоподключение...",
        "status.ble.scan_start": "Сканирование поддерживаемых BLE-контроллеров...",
        "status.ble.already_connected": "Уже подключено к {address}.",
        "status.ble.connecting": "Подключение к {address}...",
        "status.ble.color_set": "Установлен цвет RGB({red}, {green}, {blue})",
        "status.ble.brightness_set": "Яркость: {value}%",
        "status.ble.effect_applied": "Применён эффект 0x{code}",
        "status.ble.effect_speed_set": "Скорость эффекта: {value}%",
        "status.ble.scan_finished_found": "Сканирование завершено. Найдено поддерживаемых контроллеров: {count}.",
        "status.ble.scan_finished_none": "Сканирование завершено. Поддерживаемые контроллеры не найдены.",
        "status.ble.power_on": "Включение",
        "status.ble.power_off": "Выключение",
        "status.ble.brightness_restore": "Восстановлена яркость {value}",
        "status.ble.color_restore": "Восстановлен цвет RGB({red}, {green}, {blue})",
        "status.ble.driver_selected": "Выбран протокол контроллера: {driver}.",
        "status.ble.connected_via": "Подключено к {name} через {uuid}.",
        "status.ble.candidate_characteristics": "Кандидаты write-характеристик: {uuids}",
        "status.ble.disconnected": "Отключено.",
        "effect.static_color": "Статичный цвет",
        "effect.jump_rgb": "Прыжок RGB",
        "effect.jump_rgb_cmyw": "Прыжок RGB + CMY + белый",
        "effect.fade_red": "Плавное затухание: красный",
        "effect.fade_green": "Плавное затухание: зелёный",
        "effect.fade_blue": "Плавное затухание: синий",
        "effect.fade_yellow": "Плавное затухание: жёлтый",
        "effect.fade_cyan": "Плавное затухание: бирюзовый",
        "effect.fade_magenta": "Плавное затухание: пурпурный",
        "effect.fade_white": "Плавное затухание: белый",
        "effect.fade_red_green": "Плавное затухание: красный / зелёный",
        "effect.fade_red_blue": "Плавное затухание: красный / синий",
        "effect.fade_green_blue": "Плавное затухание: зелёный / синий",
        "effect.smooth_rainbow": "Плавная радуга",
        "effect.smooth_spectrum": "Плавный спектр",
        "effect.flash_red": "Мерцание: красный",
        "effect.flash_green": "Мерцание: зелёный",
        "effect.flash_blue": "Мерцание: синий",
        "effect.flash_yellow": "Мерцание: жёлтый",
        "effect.flash_cyan": "Мерцание: бирюзовый",
        "effect.flash_magenta": "Мерцание: пурпурный",
        "effect.flash_white": "Мерцание: белый",
        "effect.flash_spectrum": "Мерцание: спектр",
        "profile.azure_drift": "Лазурный дрейф",
        "profile.neon_sunset": "Неоновый закат",
        "profile.polar_mint": "Полярная мята",
        "profile.violet_pulse": "Фиолетовый импульс",
        "profile.arctic_gold": "Арктическое золото",
        "profile.pink_neon": "Розовый неон",
        "profile.northern_sky": "Северное небо",
        "profile.moon_lavender": "Лунная лаванда",
        "profile.emerald_breeze": "Изумрудный бриз",
        "profile.amber_dawn": "Янтарный рассвет",
        "slider.red": "Красный",
        "slider.green": "Зелёный",
        "slider.blue": "Синий",
        "slider.brightness": "Яркость",
        "mode.chill": "Спокойно",
        "mode.gaming": "Игры",
        "mode.night": "Ночь",
        "mode.rainbow": "Радуга",
    },
    "en": {
        "hero.title": "RGB Controller",
        "language.label": "App language",
        "hero.subtitle": "Bluetooth LED control",
        "device.title": "Device",
        "device.subtitle": "Search and connect supported BLE controllers.",
        "device.find": "Find controller",
        "device.connect": "Connect",
        "device.disconnect": "Disconnect",
        "device.show_logs": "Show logs",
        "device.hide_logs": "Hide logs",
        "device.status.not_connected": "Not connected",
        "device.status.connected": "Connected",
        "device.status.scanning": "Scanning",
        "device.status.not_found": "Controller not found",
        "device.status.found_one": "Found: {name}",
        "device.status.found_many": "Controllers found: {count}",
        "device.choice.scan_placeholder": "Scanning controllers...",
        "device.choice.not_found": "No supported controllers found",
        "color.title": "Color",
        "color.subtitle": 'Sliders change the preview. Press "Apply" to send the color to the device.',
        "color.pick": "Pick color",
        "color.apply": "Apply",
        "power.on": "Turn on",
        "power.off": "Turn off",
        "effects.title": "Effects",
        "effects.subtitle": "Static color returns to normal manual RGB control.",
        "effects.speed": "Speed",
        "configs.title": "Configs",
        "configs.subtitle": "Save favorite scenes and quickly load them back.",
        "configs.placeholder": "Example: Blue Night",
        "configs.save": "Save",
        "configs.load": "Load",
        "configs.delete": "Delete",
        "configs.reset": "Reset",
        "logs.title": "Session logs",
        "logs.subtitle": "Bluetooth technical events.",
        "theme.dark": "Dark mode",
        "theme.light": "Light mode",
        "theme.auto": "Auto theme",
        "dialog.title": "RGB Controller",
        "dialog.ok": "OK",
        "dialog.pick_color": "Choose RGB color",
        "preview.rgb": "RGB {r}, {g}, {b}  |  {brightness_label} {brightness}%",
        "error.wait_scan": "Wait until device scanning is finished.",
        "error.find_first": 'Press "Find controller" first.',
        "error.enter_profile_name": "Enter a config name.",
        "error.select_profile_first": "Select a config first.",
        "error.connect_strip_first": "Connect to the LED strip first.",
        "error.connect_strip_to_apply_profile": "Connect to the LED strip first to apply the config.",
        "status.ready_find": 'Ready. Press "Find controller" to search for supported devices.',
        "status.profile_loaded_local": "Config loaded into the interface. Connect the LED strip to apply it.",
        "status.static_color_mode": "Static color mode.",
        "status.defaults_restored": "Default configs restored.",
        "status.config_saved": 'Config "{name}" saved.',
        "status.config_loaded": 'Config "{name}" loaded.',
        "status.config_deleted": 'Config "{name}" deleted.',
        "status.autofound_connecting": "Found: {name} ({address}). Auto-connecting...",
        "status.ble.scan_start": "Scanning supported BLE controllers...",
        "status.ble.already_connected": "Already connected to {address}.",
        "status.ble.connecting": "Connecting to {address}...",
        "status.ble.color_set": "Color set to RGB({red}, {green}, {blue})",
        "status.ble.brightness_set": "Brightness set to {value}%",
        "status.ble.effect_applied": "Effect 0x{code} applied",
        "status.ble.effect_speed_set": "Effect speed set to {value}%",
        "status.ble.scan_finished_found": "Scan finished. Found {count} supported controller(s).",
        "status.ble.scan_finished_none": "Scan finished. No supported controllers found.",
        "status.ble.power_on": "Power on",
        "status.ble.power_off": "Power off",
        "status.ble.brightness_restore": "Brightness restore {value}",
        "status.ble.color_restore": "Color restore RGB({red}, {green}, {blue})",
        "status.ble.driver_selected": "Controller protocol selected: {driver}.",
        "status.ble.connected_via": "Connected to {name} via {uuid}.",
        "status.ble.candidate_characteristics": "Candidate write characteristics: {uuids}",
        "status.ble.disconnected": "Disconnected.",
        "effect.static_color": "Static color",
        "effect.jump_rgb": "RGB jump",
        "effect.jump_rgb_cmyw": "RGB + CMY + white jump",
        "effect.fade_red": "Fade: red",
        "effect.fade_green": "Fade: green",
        "effect.fade_blue": "Fade: blue",
        "effect.fade_yellow": "Fade: yellow",
        "effect.fade_cyan": "Fade: cyan",
        "effect.fade_magenta": "Fade: magenta",
        "effect.fade_white": "Fade: white",
        "effect.fade_red_green": "Fade: red / green",
        "effect.fade_red_blue": "Fade: red / blue",
        "effect.fade_green_blue": "Fade: green / blue",
        "effect.smooth_rainbow": "Smooth rainbow",
        "effect.smooth_spectrum": "Smooth spectrum",
        "effect.flash_red": "Flash: red",
        "effect.flash_green": "Flash: green",
        "effect.flash_blue": "Flash: blue",
        "effect.flash_yellow": "Flash: yellow",
        "effect.flash_cyan": "Flash: cyan",
        "effect.flash_magenta": "Flash: magenta",
        "effect.flash_white": "Flash: white",
        "effect.flash_spectrum": "Flash: spectrum",
        "profile.azure_drift": "Azure Drift",
        "profile.neon_sunset": "Neon Sunset",
        "profile.polar_mint": "Polar Mint",
        "profile.violet_pulse": "Violet Pulse",
        "profile.arctic_gold": "Arctic Gold",
        "profile.pink_neon": "Pink Neon",
        "profile.northern_sky": "Northern Sky",
        "profile.moon_lavender": "Moon Lavender",
        "profile.emerald_breeze": "Emerald Breeze",
        "profile.amber_dawn": "Amber Dawn",
        "slider.red": "Red",
        "slider.green": "Green",
        "slider.blue": "Blue",
        "slider.brightness": "Brightness",
        "mode.chill": "Chill",
        "mode.gaming": "Gaming",
        "mode.night": "Night",
        "mode.rainbow": "Rainbow",
    },
    "zh": {
        "hero.title": "RGB 控制器",
        "language.label": "界面语言",
        "hero.subtitle": "通过 Bluetooth 控制灯带",
        "device.title": "设备",
        "device.subtitle": "搜索并连接受支持的 BLE 控制器。",
        "device.find": "查找控制器",
        "device.connect": "连接",
        "device.disconnect": "断开连接",
        "device.show_logs": "显示日志",
        "device.hide_logs": "隐藏日志",
        "device.status.not_connected": "未连接",
        "device.status.connected": "已连接",
        "device.status.scanning": "正在扫描",
        "device.status.not_found": "未找到控制器",
        "device.status.found_one": "已找到：{name}",
        "device.status.found_many": "已找到控制器：{count}",
        "device.choice.scan_placeholder": "正在搜索控制器...",
        "device.choice.not_found": "未找到受支持的控制器",
        "color.title": "颜色",
        "color.subtitle": "滑块只会更新预览。点击“应用”后才会把颜色发送到设备。",
        "color.pick": "选择颜色",
        "color.apply": "应用",
        "power.on": "打开",
        "power.off": "关闭",
        "effects.title": "效果",
        "effects.subtitle": "静态颜色会返回普通的 RGB 手动控制模式。",
        "effects.speed": "速度",
        "configs.title": "配置",
        "configs.subtitle": "保存你喜欢的场景，并快速重新加载。",
        "configs.placeholder": "例如：Blue Night",
        "configs.save": "保存",
        "configs.load": "加载",
        "configs.delete": "删除",
        "configs.reset": "重置",
        "logs.title": "会话日志",
        "logs.subtitle": "Bluetooth 技术事件。",
        "theme.dark": "深色主题",
        "theme.light": "浅色主题",
        "theme.auto": "自动主题",
        "dialog.title": "RGB 控制器",
        "dialog.ok": "确定",
        "dialog.pick_color": "选择 RGB 颜色",
        "preview.rgb": "RGB {r}, {g}, {b}  |  {brightness_label} {brightness}%",
        "error.wait_scan": "请等待设备扫描完成。",
        "error.find_first": "请先点击“查找控制器”。",
        "error.enter_profile_name": "请输入配置名称。",
        "error.select_profile_first": "请先选择一个配置。",
        "error.connect_strip_first": "请先连接 LED 灯带。",
        "error.connect_strip_to_apply_profile": "请先连接 LED 灯带，然后再应用配置。",
        "status.ready_find": "准备就绪。点击“查找控制器”以搜索受支持的设备。",
        "status.profile_loaded_local": "配置已加载到界面中。请连接 LED 灯带后再应用。",
        "status.static_color_mode": "静态颜色模式。",
        "status.defaults_restored": "默认配置已恢复。",
        "status.config_saved": "配置“{name}”已保存。",
        "status.config_loaded": "配置“{name}”已加载。",
        "status.config_deleted": "配置“{name}”已删除。",
        "status.autofound_connecting": "已找到：{name} ({address})。正在自动连接...",
        "status.ble.scan_start": "正在扫描受支持的 BLE 控制器...",
        "status.ble.already_connected": "已经连接到 {address}。",
        "status.ble.connecting": "正在连接到 {address}...",
        "status.ble.color_set": "颜色设置为 RGB({red}, {green}, {blue})",
        "status.ble.brightness_set": "亮度设置为 {value}%",
        "status.ble.effect_applied": "已应用效果 0x{code}",
        "status.ble.effect_speed_set": "效果速度设置为 {value}%",
        "status.ble.scan_finished_found": "扫描完成。已找到 {count} 个受支持的控制器。",
        "status.ble.scan_finished_none": "扫描完成。未找到受支持的控制器。",
        "status.ble.power_on": "打开电源",
        "status.ble.power_off": "关闭电源",
        "status.ble.brightness_restore": "恢复亮度 {value}",
        "status.ble.color_restore": "恢复颜色 RGB({red}, {green}, {blue})",
        "status.ble.driver_selected": "已选择控制器协议：{driver}。",
        "status.ble.connected_via": "已连接到 {name}，使用 {uuid}。",
        "status.ble.candidate_characteristics": "候选可写特征: {uuids}",
        "status.ble.disconnected": "已断开连接。",
        "effect.static_color": "静态颜色",
        "effect.jump_rgb": "RGB 跳变",
        "effect.jump_rgb_cmyw": "RGB + CMY + 白色跳变",
        "effect.fade_red": "渐变淡出：红色",
        "effect.fade_green": "渐变淡出：绿色",
        "effect.fade_blue": "渐变淡出：蓝色",
        "effect.fade_yellow": "渐变淡出：黄色",
        "effect.fade_cyan": "渐变淡出：青色",
        "effect.fade_magenta": "渐变淡出：品红",
        "effect.fade_white": "渐变淡出：白色",
        "effect.fade_red_green": "渐变淡出：红 / 绿",
        "effect.fade_red_blue": "渐变淡出：红 / 蓝",
        "effect.fade_green_blue": "渐变淡出：绿 / 蓝",
        "effect.smooth_rainbow": "平滑彩虹",
        "effect.smooth_spectrum": "平滑光谱",
        "effect.flash_red": "闪烁：红色",
        "effect.flash_green": "闪烁：绿色",
        "effect.flash_blue": "闪烁：蓝色",
        "effect.flash_yellow": "闪烁：黄色",
        "effect.flash_cyan": "闪烁：青色",
        "effect.flash_magenta": "闪烁：品红",
        "effect.flash_white": "闪烁：白色",
        "effect.flash_spectrum": "闪烁：光谱",
        "profile.azure_drift": "蔚蓝漂流",
        "profile.neon_sunset": "霓虹日落",
        "profile.polar_mint": "极地薄荷",
        "profile.violet_pulse": "紫罗兰脉冲",
        "profile.arctic_gold": "北境金辉",
        "profile.pink_neon": "粉色霓虹",
        "profile.northern_sky": "北方天空",
        "profile.moon_lavender": "月光薰衣草",
        "profile.emerald_breeze": "翡翠微风",
        "profile.amber_dawn": "琥珀晨曦",
        "slider.red": "红色",
        "slider.green": "绿色",
        "slider.blue": "蓝色",
        "slider.brightness": "亮度",
        "mode.chill": "柔和",
        "mode.gaming": "游戏",
        "mode.night": "夜间",
        "mode.rainbow": "彩虹",
    },
}


class LocalizationManager:
    def __init__(self) -> None:
        self._language = "ru"

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        self._language = language if language in TRANSLATIONS else "ru"

    def t(self, key: str, **kwargs: Any) -> str:
        bundle = TRANSLATIONS.get(self._language, {})
        fallback = TRANSLATIONS["ru"]
        template = bundle.get(key) or fallback.get(key) or key
        return template.format(**kwargs) if kwargs else template

    def available_languages(self) -> list[str]:
        return [language for language in LANGUAGE_ORDER if language in LANGUAGE_LABELS]

    def language_name(self, language: str) -> str:
        return LANGUAGE_LABELS.get(language, language)

    def translation_variants(self, key: str) -> list[str]:
        variants: list[str] = []
        for bundle in TRANSLATIONS.values():
            value = bundle.get(key)
            if value and value not in variants:
                variants.append(value)
        return variants

    def effect_name(self, effect_key: str) -> str:
        return self.t(f"effect.{effect_key}")

    def profile_name(self, profile: dict[str, Any]) -> str:
        preset_key = str(profile.get("preset_key", "")).strip()
        if preset_key:
            return self.t(f"profile.{preset_key}")
        return str(profile.get("name", "")).strip()

    def profile_key_from_name(self, name: str) -> str:
        normalized = str(name).strip().casefold()
        if not normalized:
            return ""
        for bundle in TRANSLATIONS.values():
            for key, value in bundle.items():
                if key.startswith("profile.") and str(value).strip().casefold() == normalized:
                    return key.removeprefix("profile.")
        return ""

    def status_config_event(self, action: str, profile: dict[str, Any] | None = None, *, name: str | None = None) -> str:
        payload = {
            "kind": "config",
            "action": action,
            "preset_key": str((profile or {}).get("preset_key", "")).strip(),
            "name": str(name).strip() if name is not None else str((profile or {}).get("name", "")).strip(),
        }
        return L10N_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + L10N_SUFFIX

    def status_ble_event(self, event: str, **payload: Any) -> str:
        data = {"kind": "ble", "event": event, **payload}
        return L10N_PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + L10N_SUFFIX

    def normalize_error_message(self, message: str) -> str:
        lower = message.lower()
        if (
            "bluetooth radio is not powered on" in lower
            or "bleakbluetoothnotavailableerror" in lower
            or "bluetoothnotavailableerror" in lower
        ):
            if self._language == "en":
                return "Bluetooth is turned off.\nTurn it on in Windows and try again."
            if self._language == "zh":
                return "Bluetooth 已关闭。\n请在 Windows 中打开它，然后重试。"
            return "Bluetooth выключен.\nВключите его в Windows и попробуйте снова."
        if "connect to the led strip first" in lower:
            return self.t("error.connect_strip_first")
        if "device not found. make sure it is powered on and nearby." in lower:
            if self._language == "en":
                return "Device not found.\nMake sure the strip is powered on and nearby."
            if self._language == "zh":
                return "未找到设备。\n请确认灯带已通电并且就在附近。"
            return "Устройство не найдено.\nУбедитесь, что лента включена и находится рядом."
        if "no writable gatt characteristic was found on this device." in lower:
            if self._language == "en":
                return "No writable GATT characteristic was found on this device."
            if self._language == "zh":
                return "在此设备上未找到可写入的 GATT 特征。"
            return "На этом устройстве не найдена доступная для записи характеристика GATT."
        if "no supported controller protocol was detected on this device." in lower:
            if self._language == "en":
                return "This controller is not supported yet."
            if self._language == "zh":
                return "暂不支持此控制器。"
            return "Этот контроллер пока не поддерживается."
        if "built-in effects are not supported by this controller yet." in lower:
            if self._language == "en":
                return "Built-in effects are not supported by this controller yet."
            if self._language == "zh":
                return "此控制器暂不支持内置效果。"
            return "Этот контроллер пока не поддерживает встроенные эффекты."
        if "command could not be written to any compatible gatt characteristic." in lower:
            if self._language == "en":
                return "The command could not be written to any compatible GATT characteristic."
            if self._language == "zh":
                return "无法将命令写入任何兼容的 GATT 特征。"
            return "Не удалось записать команду ни в одну совместимую характеристику GATT."
        if "command could not be sent with any known protocol." in lower:
            if self._language == "en":
                return "The command could not be sent with any known protocol."
            if self._language == "zh":
                return "无法通过任何已知协议发送该命令。"
            return "Не удалось отправить команду ни через один известный протокол."
        return message

    def normalize_status_message(self, message: str) -> str:
        if message.startswith(L10N_PREFIX):
            suffix_index = message.find(L10N_SUFFIX)
            if suffix_index == -1:
                suffix_index = len(message)
                remainder = ""
            else:
                remainder = message[suffix_index + len(L10N_SUFFIX):]
            try:
                payload = json.loads(message[len(L10N_PREFIX):suffix_index])
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and payload.get("kind") == "config":
                action = str(payload.get("action", "")).strip().lower()
                preset_key = str(payload.get("preset_key", "")).strip()
                raw_name = str(payload.get("name", "")).strip()
                display_name = self.t(f"profile.{preset_key}") if preset_key else raw_name
                if action == "saved":
                    return self.t("status.config_saved", name=display_name) + remainder
                if action == "loaded":
                    return self.t("status.config_loaded", name=display_name) + remainder
                if action == "deleted":
                    return self.t("status.config_deleted", name=display_name) + remainder
            if isinstance(payload, dict) and payload.get("kind") == "ble":
                event = str(payload.get("event", "")).strip()
                if event == "scan_start":
                    return self.t("status.ble.scan_start") + remainder
                if event == "already_connected":
                    return self.t("status.ble.already_connected", address=str(payload.get("address", "")).strip()) + remainder
                if event == "connecting":
                    return self.t("status.ble.connecting", address=str(payload.get("address", "")).strip()) + remainder
                if event == "color_set":
                    return self.t(
                        "status.ble.color_set",
                        red=int(payload.get("red", 0)),
                        green=int(payload.get("green", 0)),
                        blue=int(payload.get("blue", 0)),
                    ) + remainder
                if event == "brightness_set":
                    return self.t("status.ble.brightness_set", value=int(payload.get("value", 0))) + remainder
                if event == "static_color_mode":
                    return self.t("status.static_color_mode") + remainder
                if event == "effect_applied":
                    return self.t("status.ble.effect_applied", code=str(payload.get("code", "")).strip()) + remainder
                if event == "effect_speed_set":
                    return self.t("status.ble.effect_speed_set", value=int(payload.get("value", 0))) + remainder
                if event == "scan_finished_found":
                    return self.t("status.ble.scan_finished_found", count=int(payload.get("count", 0))) + remainder
                if event == "scan_finished_none":
                    return self.t("status.ble.scan_finished_none") + remainder
                if event == "power":
                    key = "status.ble.power_on" if bool(payload.get("enabled", False)) else "status.ble.power_off"
                    return self.t(key) + remainder
                if event == "brightness_restore":
                    return self.t("status.ble.brightness_restore", value=int(payload.get("value", 0))) + remainder
                if event == "color_restore":
                    return self.t(
                        "status.ble.color_restore",
                        red=int(payload.get("red", 0)),
                        green=int(payload.get("green", 0)),
                        blue=int(payload.get("blue", 0)),
                    ) + remainder
                if event == "driver_selected":
                    return self.t("status.ble.driver_selected", driver=str(payload.get("driver", "")).strip()) + remainder
                if event == "connected_via":
                    return self.t(
                        "status.ble.connected_via",
                        name=str(payload.get("name", "")).strip(),
                        uuid=str(payload.get("uuid", "")).strip(),
                    ) + remainder
                if event == "candidate_characteristics":
                    return self.t("status.ble.candidate_characteristics", uuids=str(payload.get("uuids", "")).strip()) + remainder
                if event == "disconnected":
                    return self.t("status.ble.disconnected") + remainder

        if message in self.translation_variants("status.ready_find"):
            return self.t("status.ready_find")
        if message in self.translation_variants("status.static_color_mode"):
            return self.t("status.static_color_mode")
        if message in self.translation_variants("status.defaults_restored"):
            return self.t("status.defaults_restored")
        if message in self.translation_variants("status.profile_loaded_local"):
            return self.t("status.profile_loaded_local")

        if message in {
            "Ready. Click 'Find BLEDOM' to scan for controllers.",
            'Ready. Press "Find BLEDOM" to search for controllers.',
            "Ready. Click 'Find controller' to search for supported devices.",
            'Ready. Press "Find controller" to search for supported devices.',
        }:
            return self.t("status.ready_find")
        if message.startswith("Already connected to "):
            target = message.removeprefix("Already connected to ").removesuffix(".")
            return self.t("status.ble.already_connected", address=target)
        if message in {"Scanning for BLEDOM controllers...", "Scanning supported BLE controllers..."}:
            return self.t("status.ble.scan_start")
        if match := re.match(r"^Scan finished\. Found (\d+) BLEDOM controller\(s\)\.$", message):
            return self.t("status.ble.scan_finished_found", count=int(match.group(1)))
        if match := re.match(r"^Scan finished\. Found (\d+) supported controller\(s\)\.$", message):
            return self.t("status.ble.scan_finished_found", count=int(match.group(1)))
        if match := re.match(r"^扫描完成。已找到 (\d+) 个受支持的控制器。$", message):
            return self.t("status.ble.scan_finished_found", count=int(match.group(1)))
        if message in {"Scan finished. No BLEDOM/ELK-BLEDOM controller found.", "Scan finished. No supported controllers found."}:
            return self.t("status.ble.scan_finished_none")
        if message == "扫描完成。未找到受支持的控制器。":
            return self.t("status.ble.scan_finished_none")
        if match := re.match(r"^Found: (.+?) \((.+?)\)\. Auto-connecting\.\.\.$", message):
            name, address = match.groups()
            return self.t("status.autofound_connecting", name=name, address=address)
        if match := re.match(r"^已找到：(.+?) \((.+?)\)。正在自动连接\.\.\.$", message):
            name, address = match.groups()
            return self.t("status.autofound_connecting", name=name, address=address)
        if match := re.match(r"^Найдено устройство: (.+?) \((.+?)\)\. Автоподключение\.\.\.$", message):
            name, address = match.groups()
            return self.t("status.autofound_connecting", name=name, address=address)
        if message.startswith("Connecting to "):
            target = message.removeprefix("Connecting to ").removesuffix("...")
            return self.t("status.ble.connecting", address=target)
        if message.startswith("正在连接到 "):
            target = message.removeprefix("正在连接到 ").removesuffix("...")
            return self.t("status.ble.connecting", address=target)
        if message.startswith("Подключение к "):
            target = message.removeprefix("Подключение к ").removesuffix("...")
            return self.t("status.ble.connecting", address=target)
        if message.startswith("Controller protocol selected: "):
            driver = message.removeprefix("Controller protocol selected: ").removesuffix(".")
            return self.t("status.ble.driver_selected", driver=driver)
        if message.startswith("已选择控制器协议："):
            driver = message.removeprefix("已选择控制器协议：").removesuffix("。")
            return self.t("status.ble.driver_selected", driver=driver)
        if message.startswith("Выбран протокол контроллера: "):
            driver = message.removeprefix("Выбран протокол контроллера: ").removesuffix(".")
            return self.t("status.ble.driver_selected", driver=driver)
        if message.startswith("Connected to ") and " via " in message:
            target, via = message.removeprefix("Connected to ").split(" via ", 1)
            return self.t("status.ble.connected_via", name=target, uuid=via.removesuffix("."))
        if message.startswith("已连接到 ") and "，使用 " in message:
            target, via = message.removeprefix("已连接到 ").split("，使用 ", 1)
            return self.t("status.ble.connected_via", name=target, uuid=via.removesuffix("。"))
        if message.startswith("Подключено к ") and " через " in message:
            target, via = message.removeprefix("Подключено к ").split(" через ", 1)
            return self.t("status.ble.connected_via", name=target, uuid=via.removesuffix("."))
        if message.startswith("Candidate write characteristics: "):
            suffix = message.removeprefix("Candidate write characteristics: ")
            return self.t("status.ble.candidate_characteristics", uuids=suffix)
        if message.startswith("候选可写特征: "):
            suffix = message.removeprefix("候选可写特征: ")
            return self.t("status.ble.candidate_characteristics", uuids=suffix)
        if message.startswith("Кандидаты write-характеристик: "):
            suffix = message.removeprefix("Кандидаты write-характеристик: ")
            return self.t("status.ble.candidate_characteristics", uuids=suffix)
        if message == "Disconnected.":
            return self.t("status.ble.disconnected")
        if message == "已断开连接。":
            return self.t("status.ble.disconnected")
        if message == "Отключено.":
            return self.t("status.ble.disconnected")

        action_patterns = [
            ("Power on (", "打开电源 (", "Включение (", "status.ble.power_on"),
            ("Power off (", "关闭电源 (", "Выключение (", "status.ble.power_off"),
            ("Brightness set to ", "亮度设置为 ", "Яркость: ", "status.ble.brightness_set"),
            ("Brightness restore ", "恢复亮度 ", "Восстановлена яркость ", "status.ble.brightness_restore"),
            ("Color set to RGB(", "颜色设置为 RGB(", "Установлен цвет RGB(", "status.ble.color_set"),
            ("Color restore RGB(", "恢复颜色 RGB(", "Восстановлен цвет RGB(", "status.ble.color_restore"),
            ("Effect speed set to ", "效果速度设置为 ", "Скорость эффекта: ", "status.ble.effect_speed_set"),
        ]
        for en_prefix, zh_prefix, ru_prefix, key in action_patterns:
            for prefix in (en_prefix, zh_prefix, ru_prefix):
                if message.startswith(prefix):
                    suffix = message[len(prefix):]
                    if key == "status.ble.brightness_set":
                        return self.t("status.ble.brightness_set", value=suffix.removesuffix("%"))
                    if key == "status.ble.brightness_restore":
                        return self.t("status.ble.brightness_restore", value=suffix)
                    if key == "status.ble.effect_speed_set":
                        return self.t("status.ble.effect_speed_set", value=suffix.removesuffix("%"))
                    if key == "status.ble.power_on":
                        return self.t("status.ble.power_on") + suffix
                    if key == "status.ble.power_off":
                        return self.t("status.ble.power_off") + suffix
                    head = self.t(key, red="", green="", blue="")
                    rgb_prefix = head.split("RGB(")[0] if "RGB(" in head else head
                    return rgb_prefix + suffix

        effect_patterns = [
            r"Effect\s+(0x[0-9a-fA-F]+)\s+applied\s*(\(.+)?",
            r"已应用效果\s*(0x[0-9a-fA-F]+)\s*(\(.+)?",
            r"Эффект\s*(0x[0-9a-fA-F]+)\s*применён\s*(\(.+)?",
        ]
        for pattern in effect_patterns:
            match = re.match(pattern, message)
            if match:
                code = match.group(1)
                return self.t("status.ble.effect_applied", code=code)

        if message in {"Static color mode.", "Static color mode selected."}:
            return self.t("status.static_color_mode")
        if message in {"Defaults restored.", "Default configs restored."}:
            return self.t("status.defaults_restored")
        if message in {
            "Profile loaded locally. Connect to the LED strip to apply it.",
            "Config loaded into the interface. Connect the LED strip to apply it.",
        }:
            return self.t("status.profile_loaded_local")

        if message.startswith("Config '") and message.endswith("' saved."):
            name = message.removeprefix("Config '").removesuffix("' saved.")
            return self.normalize_status_message(self.status_config_event("saved", name=name))
        if message.startswith("Config '") and message.endswith("' loaded."):
            name = message.removeprefix("Config '").removesuffix("' loaded.")
            return self.normalize_status_message(self.status_config_event("loaded", name=name))
        if message.startswith("Config '") and message.endswith("' deleted."):
            name = message.removeprefix("Config '").removesuffix("' deleted.")
            return self.normalize_status_message(self.status_config_event("deleted", name=name))

        ru_match = re.fullmatch(r"Конфиг «(.+?)» (сохранён|загружен|удалён)\.", message)
        if ru_match:
            raw_name, action_text = ru_match.groups()
            action_map = {"сохранён": "saved", "загружен": "loaded", "удалён": "deleted"}
            return self.normalize_status_message(self.status_config_event(action_map[action_text], name=raw_name))

        zh_match = re.fullmatch(r"配置“(.+?)”已(保存|加载|删除)。", message)
        if zh_match:
            raw_name, action_text = zh_match.groups()
            action_map = {"保存": "saved", "加载": "loaded", "删除": "deleted"}
            return self.normalize_status_message(self.status_config_event(action_map[action_text], name=raw_name))

        if message.startswith("BLE error: "):
            return f"{self.t('error.ble_prefix')}{self.normalize_error_message(message.removeprefix('BLE error: '))}"
        if message.startswith("BLE 错误："):
            return f"{self.t('error.ble_prefix')}{self.normalize_error_message(message.removeprefix('BLE 错误：'))}"
        if message.startswith("Ошибка BLE: "):
            return f"{self.t('error.ble_prefix')}{self.normalize_error_message(message.removeprefix('Ошибка BLE: '))}"
        return message


localization_manager = LocalizationManager()
