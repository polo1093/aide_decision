"""Auto-click and target-button highlighting helpers for the launcher app."""

from __future__ import annotations

import queue
import time
import tkinter as tk
from typing import Optional

from launch_support import (
    AUTO_CLICK_ARM_DELAY_SECONDS,
    AUTO_CLICK_COMMAND_TTL_SECONDS,
    AUTO_CLICK_RETRY_SECONDS,
    TargetActionCommand,
    _lighten_hex,
    _target_button_bbox,
)
from objet.services.controller import ControllerViewState
from objet.utils.logging_config import get_logger


logger = get_logger(__name__)


def _launcher_module():
    import launch

    return launch


class AppClickMixin:
    """Auto-click queue, hotkey, and button highlight behaviour."""

    def _target_button_screen_bbox(self, target_button: Optional[dict[str, object]]) -> Optional[tuple[int, int, int, int]]:
        bbox = _target_button_bbox(target_button)
        if bbox is None:
            return None

        dx, dy = self._runtime_region_offset()
        x, y, width, height = bbox
        return x + dx, y + dy, width, height

    def _runtime_region_offset(self) -> tuple[int, int]:
        table = getattr(getattr(self.controller, "game", None), "table", None)
        scan = getattr(table, "scan", None)
        offset = getattr(scan, "runtime_region_offset", (0, 0))
        if not isinstance(offset, (list, tuple)) or len(offset) < 2:
            return 0, 0
        try:
            return int(round(float(offset[0]))), int(round(float(offset[1])))
        except (TypeError, ValueError):
            return 0, 0

    def _on_button_highlight_option_changed(self) -> None:
        if not self.var_show_button_highlight.get():
            self._hide_button_highlight()
            return

        state = getattr(self.controller, "last_view_state", None)
        if isinstance(state, ControllerViewState):
            self._update_button_highlight(state.target_button)

    def _toggle_auto_click(self) -> None:
        self.var_auto_click_target.set(not self.var_auto_click_target.get())
        self._on_auto_click_option_changed()

    def _on_auto_click_option_changed(self) -> None:
        if not self.var_auto_click_target.get():
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self._auto_click_ready_at = 0.0
            self._cancel_auto_click_timer()
            self._clear_pending_clicks()
            self.var_click_status.set("clic: off")
            return

        self._last_click_signature = None
        self._last_click_queued_at = 0.0
        self._auto_click_ready_at = time.monotonic() + AUTO_CLICK_ARM_DELAY_SECONDS
        self.var_click_status.set(f"clic: arme dans {AUTO_CLICK_ARM_DELAY_SECONDS:.1f}s")
        self._schedule_auto_click_ready_check(AUTO_CLICK_ARM_DELAY_SECONDS)

    def _maybe_queue_target_click(self, state: ControllerViewState) -> None:
        if not self.var_auto_click_target.get():
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self.var_click_status.set("clic: off")
            return

        if not state.scan_ok:
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self._clear_pending_clicks()
            self.var_click_status.set("clic: table absente")
            return

        wait_remaining = self._auto_click_wait_remaining()
        if wait_remaining > 0:
            self.var_click_status.set(f"clic: arme dans {wait_remaining:.1f}s")
            self._schedule_auto_click_ready_check(wait_remaining)
            return

        if state.decision_action == "WAIT":
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self._clear_pending_clicks()
            self.var_click_status.set("clic: attente decision")
            return

        click_box = self._target_button_screen_bbox(state.target_button)
        if click_box is None:
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self._clear_pending_clicks()
            self.var_click_status.set("clic: pret")
            return

        if state.decision_action == "FOLD":
            if not self._fold_has_positive_call(state):
                self._last_click_signature = None
                self._last_click_queued_at = 0.0
                self._clear_pending_clicks()
                self.var_click_status.set("clic: fold bloque sans call")
                return

        signature = self._click_signature(state, click_box)
        now = time.monotonic()
        elapsed = now - self._last_click_queued_at
        if signature == self._last_click_signature and elapsed < AUTO_CLICK_RETRY_SECONDS:
            return

        self._last_click_signature = signature
        self._last_click_queued_at = now
        command = TargetActionCommand(
            click_box=click_box,
            game_name=state.game_name,
            decision_action=state.decision_action,
            raise_amount=self._target_raise_amount(state),
            runtime_offset=self._runtime_region_offset(),
            hand_id=state.hand_id,
            street=state.street,
            target_button_label=str((state.target_button or {}).get("label", "")),
            target_button_state=str((state.target_button or {}).get("state", "")),
            target_button_value=self._target_button_value(state.target_button),
            queued_at=now,
        )
        self._click_queue.put(command)
        self._auto_click_ready_at = 0.0
        self._cancel_auto_click_timer()
        self.var_click_status.set(self._queued_click_status(command))

    def _click_signature(
        self,
        state: ControllerViewState,
        click_box: tuple[int, int, int, int],
    ) -> tuple[object, ...]:
        target = state.target_button or {}
        return (
            state.hand_id,
            state.decision_action,
            state.raise_amount,
            target.get("label"),
            target.get("state"),
            click_box,
        )

    def _click_worker_loop(self) -> None:
        while not self._click_worker_stop.is_set():
            try:
                command = self._click_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if command is None:
                continue
            try:
                self._execute_target_action(command)
            except Exception as exc:
                logger.exception("erreur_clic_bouton_cible command=%s", command)
                self.after(0, lambda exc=exc: self.var_click_status.set(f"clic: erreur {exc}"))
            else:
                self.after(0, lambda command=command: self.var_click_status.set(f"clic: fait {command.click_box}"))

    def _execute_target_action(self, command: TargetActionCommand) -> None:
        if not self._queued_command_is_current(command):
            logger.warning("clic_ignore_commande_perimee command=%s", command)
            return
        if command.decision_action == "RAISE" and command.raise_amount is not None:
            typed = _launcher_module().enter_raise_amount_for_game(
                command.game_name,
                command.raise_amount,
                runtime_offset=command.runtime_offset,
            )
            if typed:
                logger.info(
                    "raise_amount_envoye game=%s amount=%s text=%s",
                    command.game_name,
                    command.raise_amount,
                    typed,
                )
        self._left_click_box_center(command.click_box)

    def _left_click_box_center(self, click_box: tuple[int, int, int, int]) -> None:
        x, y, width, height = click_box
        if width <= 0 or height <= 0:
            return

        _launcher_module().click_target_button_box((x, y, width, height))

    def _queued_command_is_current(self, command: TargetActionCommand) -> bool:
        queued_at = getattr(command, "queued_at", 0.0) or 0.0
        if queued_at and time.monotonic() - queued_at > AUTO_CLICK_COMMAND_TTL_SECONDS:
            return False

        state = getattr(self.controller, "last_view_state", None)
        if not isinstance(state, ControllerViewState):
            return False
        if not state.scan_ok:
            return False
        if state.hand_id != command.hand_id:
            return False
        if state.street != command.street:
            return False
        if state.decision_action != command.decision_action:
            return False

        target = state.target_button or {}
        if str(target.get("label", "")) != command.target_button_label:
            return False
        if str(target.get("state", "")) != command.target_button_state:
            return False
        queued_value = getattr(command, "target_button_value", None)
        if queued_value is not None:
            current_value = self._target_button_value(target)
            if current_value is None or abs(current_value - queued_value) >= 0.01:
                return False
        if self._target_button_screen_bbox(target) != command.click_box:
            return False

        if command.decision_action == "RAISE":
            try:
                current_raise = float(state.raise_amount)
                queued_raise = float(command.raise_amount)
            except (TypeError, ValueError):
                return command.raise_amount is None and state.raise_amount is None
            return abs(current_raise - queued_raise) < 0.01
        return True

    @staticmethod
    def _target_button_value(target_button: Optional[dict[str, object]]) -> Optional[float]:
        try:
            return float((target_button or {}).get("value"))
        except (TypeError, ValueError):
            return None

    def _target_raise_amount(self, state: ControllerViewState) -> Optional[float]:
        if state.decision_action != "RAISE":
            return None
        try:
            amount = float(state.raise_amount)
        except (TypeError, ValueError):
            return None
        return amount if amount > 0 else None

    def _fold_has_positive_call(self, state: ControllerViewState) -> bool:
        try:
            return float(state.to_call) > 0
        except (TypeError, ValueError):
            return False

    def _queued_click_status(self, command: TargetActionCommand) -> str:
        if command.decision_action == "RAISE" and command.raise_amount is not None:
            return f"clic: queue raise {command.raise_amount} {command.click_box}"
        return f"clic: queue {command.click_box}"

    def _stop_click_worker(self) -> None:
        self._click_worker_stop.set()
        self._click_queue.put(None)
        if self._click_worker.is_alive():
            self._click_worker.join(timeout=1.0)

    def _clear_pending_clicks(self) -> None:
        try:
            while True:
                self._click_queue.get_nowait()
        except queue.Empty:
            return

    def _auto_click_wait_remaining(self) -> float:
        ready_at = self.__dict__.get("_auto_click_ready_at", 0.0)
        if ready_at <= 0:
            return 0.0
        return max(0.0, ready_at - time.monotonic())

    def _schedule_auto_click_ready_check(self, delay_seconds: float) -> None:
        self._cancel_auto_click_timer()
        delay_ms = max(1, int(delay_seconds * 1000))
        self._auto_click_after_id = self.after(delay_ms, self._try_auto_click_current_state)

    def _cancel_auto_click_timer(self) -> None:
        after_id = self.__dict__.get("_auto_click_after_id")
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except Exception:
            pass
        self._auto_click_after_id = None

    def _try_auto_click_current_state(self) -> None:
        self._auto_click_after_id = None
        if not self.var_auto_click_target.get():
            return
        state = getattr(self.controller, "last_view_state", None)
        if isinstance(state, ControllerViewState):
            self._maybe_queue_target_click(state)
        else:
            self.var_click_status.set("clic: pret")

    def _register_click_hotkey(self) -> None:
        try:
            import keyboard

            self._click_hotkey = keyboard.add_hotkey(
                "f12",
                lambda: self.after(0, self._toggle_auto_click),
            )
        except Exception as exc:
            logger.warning("hotkey_f12_global_indisponible error=%s", exc)
            self._click_hotkey = None
            self.bind("<F12>", lambda _e: self._toggle_auto_click())

    def _unregister_click_hotkey(self) -> None:
        if self._click_hotkey is None:
            return
        try:
            import keyboard

            keyboard.remove_hotkey(self._click_hotkey)
        except Exception as exc:
            logger.warning("hotkey_f12_global_suppression_impossible error=%s", exc)
        self._click_hotkey = None

    def _show_button_highlight(self, bbox: tuple[int, int, int, int]) -> None:
        x, y, width, height = bbox
        if width <= 0 or height <= 0:
            self._hide_button_highlight()
            return

        color = "#ffd400"
        pad = 8
        thickness = 5
        segments = [
            (x - pad, y - pad, width + 2 * pad, thickness),
            (x - pad, y + height + pad - thickness, width + 2 * pad, thickness),
            (x - pad, y - pad, thickness, height + 2 * pad),
            (x + width + pad - thickness, y - pad, thickness, height + 2 * pad),
        ]

        windows = self._ensure_button_highlight_windows()
        for window, (sx, sy, sw, sh) in zip(windows, segments):
            window.configure(bg=color)
            window.geometry(f"{max(1, sw)}x{max(1, sh)}+{int(sx)}+{int(sy)}")
            window.deiconify()
            window.lift()

    def _ensure_button_highlight_windows(self) -> list[tk.Toplevel]:
        if self._button_highlight_windows:
            return self._button_highlight_windows

        for _ in range(4):
            window = tk.Toplevel(self)
            window.withdraw()
            window.overrideredirect(True)
            window.configure(bg="#ffd400")
            window.attributes("-topmost", True)
            self._button_highlight_windows.append(window)
        return self._button_highlight_windows

    def _hide_button_highlight(self) -> None:
        for window in self._button_highlight_windows:
            if window.winfo_exists():
                window.withdraw()

    def _set_decision_color(self, action: str, *, blink: bool = False) -> None:
        colors = {
            "WAIT": "#6c757d",
            "FOLD": "#b02a37",
            "CALL": "#0d6efd",
            "CHECK": "#198754",
            "RAISE": "#b26a00",
        }
        self._base_decision_color = colors.get(action, "#6c757d")
        if blink:
            self._start_decision_blink()
        else:
            self._stop_decision_blink()
            self.lbl_decision.configure(bg=self._base_decision_color)

    def _start_decision_blink(self) -> None:
        if self._blink_after_id is not None:
            return
        self._blink_on = False
        self._blink_decision()

    def _blink_decision(self) -> None:
        self._blink_on = not self._blink_on
        color = _lighten_hex(self._base_decision_color, 0.18) if self._blink_on else self._base_decision_color
        self.lbl_decision.configure(bg=color)
        self._blink_after_id = self.after(450, self._blink_decision)

    def _stop_decision_blink(self) -> None:
        if self._blink_after_id is not None:
            self.after_cancel(self._blink_after_id)
            self._blink_after_id = None
        self._blink_on = False
