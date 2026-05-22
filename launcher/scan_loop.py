"""Continuous scan loop helpers for the launcher app."""

from __future__ import annotations

import queue
import threading
import time

from launch_support import _fmt_optional_float
from objet.services.controller import ControllerViewState
from objet.utils.logging_config import get_logger


logger = get_logger(__name__)


class AppScanMixin:
    """Snapshot and continuous scan execution for the Tkinter launcher."""

    def start_scan(self) -> None:
        self._update_interval()
        if self.scanning:
            logger.info("scan_continu deja_actif interval_ms=%s", self.scan_interval_ms)
            return
        self.scanning = True
        self._last_tick_t = time.time()
        logger.info("debut scan_continu interval_ms=%s", self.scan_interval_ms)
        self.after(1, self._tick)

    def stop_scan(self) -> None:
        if self.scanning:
            logger.info("fin scan_continu last_ms=%s", _fmt_optional_float(self.last_call_ms))
        self.scanning = False
        self._stop_decision_blink()
        self._hide_button_highlight()

    def snapshot_once(self) -> None:
        logger.info("debut snapshot")
        state, dt_ms = self._run_controller(context="Snapshot")
        self.last_call_ms = dt_ms
        self.fps = None
        self._apply_view_state(state)
        self.var_perf.set(f"scan: {dt_ms:.1f} ms | fps: ---")
        logger.info("fin snapshot status=ok duree_ms=%.1f", dt_ms)

    def _tick(self) -> None:
        if not self.scanning:
            return

        if self._scan_in_flight:
            self._schedule_scan_poll()
            return

        self._scan_in_flight = True
        self.var_perf.set("scan: en cours | fps: " + (f"{self.fps:.1f}" if self.fps else "---"))
        thread = threading.Thread(
            target=self._run_controller_worker,
            name="scan-controller-worker",
            daemon=True,
        )
        thread.start()
        self._schedule_scan_poll()

    def _run_controller_worker(self) -> None:
        t0 = time.perf_counter()
        try:
            state = self.controller.run_cycle()
        except Exception as exc:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self._scan_result_queue.put(("error", exc, dt_ms))
            return
        dt_ms = (time.perf_counter() - t0) * 1000.0
        self._scan_result_queue.put(("ok", state, dt_ms))

    def _schedule_scan_poll(self) -> None:
        if self._scan_poll_after_id is None:
            self._scan_poll_after_id = self.after(25, self._poll_scan_result)

    def _poll_scan_result(self) -> None:
        self._scan_poll_after_id = None
        try:
            status, payload, dt_ms = self._scan_result_queue.get_nowait()
        except queue.Empty:
            if self._scan_in_flight:
                self._schedule_scan_poll()
            return

        self._scan_in_flight = False
        self.last_call_ms = dt_ms

        if status == "error":
            self.scanning = False
            error = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
            self._handle_controller_exception(context="Scan continu", error=error)
            return

        if not self.scanning:
            return

        state = payload
        if not isinstance(state, ControllerViewState):
            self.scanning = False
            self._handle_controller_exception(
                context="Scan continu",
                error=TypeError(f"Etat de scan inattendu: {type(state)!r}"),
            )
            return
        self._apply_scan_result(state, dt_ms)

        if self.scanning:
            self._update_interval()
            next_delay = max(50, self.scan_interval_ms - int(dt_ms))
            self.after(next_delay, self._tick)

    def _apply_scan_result(self, state: ControllerViewState, dt_ms: float) -> None:
        self.last_call_ms = dt_ms

        now = time.time()
        if self._last_tick_t is not None:
            dt_s = max(now - self._last_tick_t, 1e-6)
            self.fps = 1.0 / dt_s
        else:
            self.fps = None
        self._last_tick_t = now

        self._apply_view_state(state)
        self._maybe_auto_identify_cards(state)
        fps_txt = f"{self.fps:.1f}" if self.fps else "---"
        self.var_perf.set(f"scan: {dt_ms:.1f} ms | fps: {fps_txt}")

    def _run_controller(self, *, context: str) -> tuple[ControllerViewState, float]:
        t0 = time.perf_counter()
        try:
            state = self.controller.run_cycle()
        except Exception as exc:
            self._handle_controller_exception(context=context, error=exc)
            raise
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return state, dt_ms
