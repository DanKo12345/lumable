from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from app.panels.types import PanelHost
from app.widgets import GlassCard
from app.widgets.themed_line_edit import ThemedLineEdit


def _row(host: PanelHost) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(host._sz(10))
    return row


def _label(host: PanelHost, key: str, *, width: int | None = None) -> QLabel:
    label = QLabel(host._tr(key))
    label.setObjectName("sliderLabel")
    if width is not None:
        label.setMinimumWidth(host._sz(width))
    return label


def build_local_api_section(host: PanelHost) -> GlassCard:
    """Local HTTP API: a control surface for Home Assistant / Stream Deck /
    scripts. Off by default, loopback-only, token-protected. The everyday view is
    just Enable + status; the token, port and LAN access live under Advanced so
    the card doesn't look like a developer panel."""
    host.api_card = host._card(host._tr("api.title"), host._tr("api.subtitle"), icon="network")

    # ── Everyday view: enable + live status (+ reveal eye when on LAN) ──
    top = _row(host)
    host.api_enable_button = host._button(host._tr("api.off_button"), "ghost")
    host.api_enable_button.setCheckable(True)
    host.api_enable_button.setMinimumWidth(host._sz(120))
    host.api_status_label = QLabel(host._tr("api.status_off"))
    host.api_status_label.setObjectName("timerConnect")
    host.api_status_label.setWordWrap(True)
    top.addWidget(host.api_enable_button, 0, Qt.AlignVCenter)
    top.addWidget(host.api_status_label, 1, Qt.AlignVCenter)
    host.api_card.content_layout.addLayout(top)

    # ── "How to connect" (primary next step) + Advanced toggle ─────────
    actions_row = _row(host)
    host.api_help_button = host._button(host._tr("api.help"), "accent_soft")
    actions_row.addWidget(host.api_help_button, 0, Qt.AlignVCenter)
    # Shown only when the API is reachable over the network (a phone can open it).
    host.api_pair_button = host._button(host._tr("api.pair"), "ghost")
    host.api_pair_button.setVisible(False)
    actions_row.addWidget(host.api_pair_button, 0, Qt.AlignVCenter)
    actions_row.addStretch(1)
    host.api_advanced_toggle = host._button(host._tr("api.advanced"), "ghost")
    host.api_advanced_toggle.setCheckable(True)
    actions_row.addWidget(host.api_advanced_toggle, 0, Qt.AlignVCenter)
    host.api_card.content_layout.addLayout(actions_row)

    # ── Paired phones: count + "disconnect all" (shown only when a phone is on) ─
    phones_row = _row(host)
    host.api_phones_label = QLabel(host._tr("api.phones_connected", count=0))
    host.api_phones_label.setObjectName("timerConnect")
    host.api_phones_label.setVisible(False)
    host.api_disconnect_phones_button = host._button(host._tr("api.disconnect_phones"), "ghost")
    host.api_disconnect_phones_button.setVisible(False)
    phones_row.addWidget(host.api_phones_label, 1, Qt.AlignVCenter)
    phones_row.addWidget(host.api_disconnect_phones_button, 0, Qt.AlignVCenter)
    host.api_card.content_layout.addLayout(phones_row)

    # ── Advanced container (hidden by default) ─────────────────────────
    host.api_advanced_container = QWidget()
    advanced = QVBoxLayout(host.api_advanced_container)
    advanced.setContentsMargins(0, host._sz(4), 0, 0)
    advanced.setSpacing(host._sz(8))

    # Token: masked field, with its actions visually kept beneath the field.
    token_row = _row(host)
    host.api_token_label = _label(host, "api.token", width=90)
    token_row.addWidget(host.api_token_label, 0, Qt.AlignVCenter)
    host.api_token_field = ThemedLineEdit()
    host.api_token_field.setReadOnly(True)
    host.api_token_field.setMinimumWidth(host._sz(150))
    token_row.addWidget(host.api_token_field, 1, Qt.AlignVCenter)
    advanced.addLayout(token_row)

    token_buttons = _row(host)
    token_buttons.addSpacing(host._sz(100))
    host.api_copy_token_button = host._button(host._tr("api.copy_token"), "ghost")
    host.api_regenerate_button = host._button(host._tr("api.regenerate"), "ghost")
    token_buttons.addWidget(host.api_copy_token_button, 0, Qt.AlignVCenter)
    token_buttons.addWidget(host.api_regenerate_button, 0, Qt.AlignVCenter)
    advanced.addLayout(token_buttons)

    # Port.
    port_row = _row(host)
    host.api_port_label = _label(host, "api.port", width=90)
    port_row.addWidget(host.api_port_label, 0, Qt.AlignVCenter)
    host.api_port_field = ThemedLineEdit()
    host.api_port_field.setFixedWidth(host._sz(110))
    port_row.addWidget(host.api_port_field, 0, Qt.AlignVCenter)
    port_row.addStretch(1)
    advanced.addLayout(port_row)

    # LAN access — dangerous, off by default. The IP auto-fills on enable.
    lan_row = _row(host)
    host.api_lan_button = host._button(host._tr("api.allow_lan"), "ghost")
    host.api_lan_button.setCheckable(True)
    host.api_lan_button.setMinimumWidth(host._sz(150))
    host.api_lan_host_field = ThemedLineEdit()
    host.api_lan_host_field.setPlaceholderText(host._tr("api.lan_host_placeholder"))
    host.api_lan_host_field.setMinimumWidth(host._sz(150))
    host.api_lan_host_field.setEchoMode(QLineEdit.Password)  # masked until revealed
    # Eye toggle sits right next to the address field so it reads as "reveal this".
    host.api_reveal_button = host._button("", "ghost")
    host.api_reveal_button.setCheckable(True)
    host.api_reveal_button.set_icon_kind("eye")
    host.api_reveal_button.setIconSize(QSize(18, 18))
    host.api_reveal_button.setFixedSize(host._sz(38), host._sz(38))
    host.api_reveal_button.setToolTip(host._tr("api.reveal"))
    lan_row.addWidget(host.api_lan_button, 0, Qt.AlignVCenter)
    lan_row.addWidget(host.api_lan_host_field, 1, Qt.AlignVCenter)
    lan_row.addWidget(host.api_reveal_button, 0, Qt.AlignVCenter)
    advanced.addLayout(lan_row)

    host.api_lan_warning = QLabel(host._tr("api.lan_warning"))
    host.api_lan_warning.setObjectName("diagnosticsSupportHint")
    host.api_lan_warning.setWordWrap(True)
    host.api_lan_warning.setVisible(False)
    advanced.addWidget(host.api_lan_warning)

    host.api_advanced_container.setVisible(False)
    host.api_card.content_layout.addWidget(host.api_advanced_container)

    # Short "how it works" note, always visible.
    host.api_security_note = QLabel(host._tr("api.security_note"))
    host.api_security_note.setObjectName("timerConnect")
    host.api_security_note.setWordWrap(True)
    host.api_card.content_layout.addWidget(host.api_security_note)

    return host.api_card
