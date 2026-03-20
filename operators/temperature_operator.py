from datetime import datetime
from time import sleep, monotonic

from hardware import AnnealerController
from models import ResultRunData
from services import Logger, AppConfig, PIDCalculator


class RunStopped(Exception):
    pass


class TemperatureOperator:
    def __init__(
        self,
        temperature_profile,
        result_run,
        db,
        time_at_temperature,
        actual_temperature,
        target_temperature,
        temperature_last_update,
        shared_lock,
        stop_event=None,
        error_callback=None,
    ):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.result_run = result_run
        self.temperature_profile = temperature_profile

        self.time_at_temperature = time_at_temperature
        self.actual_temperature = actual_temperature
        self.target_temperature = target_temperature
        self.temperature_last_update = temperature_last_update
        self.shared_lock = shared_lock
        self.stop_event = stop_event
        self.error_callback = error_callback

        self.result_set = self.db.get_result_set_by_id(self.result_run.result_set_id)
        self.experiment = self.db.get_experiment_by_id(self.result_run.experiment_id)

        self.annealer_controller = AnnealerController()

        if not self.annealer_controller.connect():
            raise RuntimeError("Failed to connect to annealer; aborting temperature operator setup")

        self.logger.info("Annealer connected")
        serial_number = self.annealer_controller.get_serial_number()
        self.annealer_parameters = self.db.get_annealer_by_serial_number(serial_number)
        if not self.annealer_parameters:
            raise RuntimeError(f"Annealer serial {serial_number} not found in database")

        self.result_run.annealer_id = self.annealer_parameters.id

    def request_stop(self, reason="Temperature control stop requested"):
        self.logger.warning(reason)
        if self.stop_event is not None:
            self.stop_event.set()

    def run(self):
        max_intensity = int(self.app_config.get("max_heat_intensity"))
        tolerance_c = float(self.app_config.get("temperature_target_tolerance", 0.2))
        tolerance_hysteresis_c = float(self.app_config.get("temperature_target_hysteresis", 0.1))
        reset_grace_s = float(self.app_config.get("temperature_target_reset_grace_seconds", 5.0))
        loop_period_s = float(self.app_config.get("temperature_poll_interval_seconds", 1.0))

        self.logger.info(
            f"Started temperature run for experiment {self.experiment.id} with result set {self.result_set.id}"
        )

        pid_calculators = {}
        time_target_temperature_reached = {}
        out_of_band_started = {}
        last_target_temperature = {}
        last_update_time = {}

        for sample in self.experiment.sample:
            pid_calculators[sample.id] = PIDCalculator(
                self.result_run.pid_kp,
                self.result_run.pid_ki,
                self.result_run.pid_kd,
            )
            now_dt = datetime.now()
            last_update_time[sample.id] = now_dt
            time_target_temperature_reached[sample.id] = None
            out_of_band_started[sample.id] = None

        try:
            terminal_statuses = {"Complete", "Failed", "Aborted"}
            active_statuses = {"Running", "Paused"}

            while True:
                self._raise_if_stopped()
                current_status = self.result_run.status
                if current_status in terminal_statuses:
                    break
                if current_status not in active_statuses:
                    sleep(loop_period_s)
                    continue

                cycle_started = datetime.now()
                result_rows = []

                for sample in self.experiment.sample:
                    self._raise_if_stopped()

                    well_row = sample.well_row
                    well_column = sample.well_column

                    annealer_well = next(
                        (
                            well for well in self.annealer_parameters.wells
                            if well.well_row == well_row and well.well_column == well_column
                        ),
                        None,
                    )

                    if annealer_well is None:
                        raise RuntimeError(
                            f"No annealer mapping found for sample {sample.id} in well {well_row}{well_column}"
                        )

                    sensor_address = annealer_well.sensor_address
                    if not sensor_address:
                        raise RuntimeError(
                            f"No sensor address for sample {sample.id} in well {well_row}{well_column}"
                        )

                    calibration_offset = annealer_well.calibration_factor
                    heater_index = annealer_well.well_index

                    current_time = datetime.now()
                    dt = max((current_time - last_update_time[sample.id]).total_seconds(), 1e-3)
                    last_update_time[sample.id] = current_time

                    current_temp = self.annealer_controller.get_temperature_celsius(
                        sensor_address=sensor_address,
                        calibration_factor=calibration_offset,
                    )

                    if current_temp is None:
                        self.logger.error(
                            f"Failed to read temperature for sample {sample.id} at well {well_row}{well_column}"
                        )
                        continue

                    sample_update_mono = monotonic()
                    if self.shared_lock is None:
                        self.actual_temperature[sample.id] = current_temp
                        self.temperature_last_update[sample.id] = sample_update_mono
                        target_temp = self.target_temperature[sample.id]
                    else:
                        with self.shared_lock:
                            self.actual_temperature[sample.id] = current_temp
                            self.temperature_last_update[sample.id] = sample_update_mono
                            target_temp = self.target_temperature[sample.id]

                    previous_target = last_target_temperature.get(sample.id)
                    if previous_target is None or abs(target_temp - previous_target) > 1e-9:
                        time_target_temperature_reached[sample.id] = None
                        out_of_band_started[sample.id] = None
                        if self.shared_lock is None:
                            self.time_at_temperature[sample.id] = 0
                        else:
                            with self.shared_lock:
                                self.time_at_temperature[sample.id] = 0
                    last_target_temperature[sample.id] = target_temp

                    error = target_temp - current_temp
                    abs_error = abs(error)
                    now_mono = monotonic()
                    enter_band_tol = tolerance_c
                    exit_band_tol = tolerance_c + max(0.0, tolerance_hysteresis_c)
                    start_time = time_target_temperature_reached[sample.id]
                    out_since = out_of_band_started[sample.id]

                    if start_time is None:
                        if abs_error <= enter_band_tol:
                            time_target_temperature_reached[sample.id] = now_mono
                            out_of_band_started[sample.id] = None
                            seconds_at_target = 0
                        else:
                            seconds_at_target = 0
                    else:
                        if abs_error <= exit_band_tol:
                            if out_since is not None:
                                # Exclude brief out-of-band excursions from soak timing.
                                time_target_temperature_reached[sample.id] += max(0.0, now_mono - out_since)
                                out_of_band_started[sample.id] = None
                                start_time = time_target_temperature_reached[sample.id]
                            seconds_at_target = int(max(0.0, now_mono - start_time))
                        else:
                            if out_since is None:
                                out_of_band_started[sample.id] = now_mono
                                out_since = now_mono
                            if now_mono - out_since >= reset_grace_s:
                                time_target_temperature_reached[sample.id] = None
                                out_of_band_started[sample.id] = None
                                seconds_at_target = 0
                                self.logger.warning(
                                    f"Soak timer reset for sample {sample.id}: "
                                    f"out of tolerance for {reset_grace_s:.1f}s "
                                    f"(target {target_temp:.2f} C, actual {current_temp:.2f} C)."
                                )
                            else:
                                # Hold timer during short excursions; only sustained drift resets.
                                seconds_at_target = int(max(0.0, out_since - start_time))

                    if self.shared_lock is None:
                        self.time_at_temperature[sample.id] = seconds_at_target
                    else:
                        with self.shared_lock:
                            self.time_at_temperature[sample.id] = seconds_at_target

                    if error > 1.0:
                        intensity = max_intensity
                        pid_calculators[sample.id].reset()
                    elif error < -1.0:
                        intensity = 0
                        pid_calculators[sample.id].reset()
                    else:
                        pid_output, _, _, _ = pid_calculators[sample.id].update(error, dt)
                        intensity = max(0, min(int(pid_output), max_intensity))

                    self.annealer_controller.apply_heat(index=heater_index, intensity=intensity)

                    elapsed_seconds = int((current_time - self.result_run.start_date_time).total_seconds())
                    elapsed_minutes = int(elapsed_seconds / 60)

                    result_rows.append(
                        ResultRunData(
                            sample_id=sample.id,
                            result_run_id=self.result_run.id,
                            reading_date_time=current_time,
                            target_temperature=target_temp,
                            elapsed_minutes=elapsed_minutes,
                            actual_temperature=current_temp,
                            heat_applied=intensity,
                        )
                    )

                self.db.add_result_run_data_batch(result_rows)

                elapsed = (datetime.now() - cycle_started).total_seconds()
                sleep(max(0.0, loop_period_s - elapsed))

        except RunStopped:
            if self.result_run.status == "Running":
                self.result_run.status = "Aborted"
            self.logger.warning("Temperature control stopped.")

        except Exception as exc:
            self.result_run.status = "Failed"
            self.logger.error(f"Temperature run failed: {exc}")
            self._notify_error("temperature", exc)

        finally:
            try:
                self.annealer_controller.zero_all_wells()
                self.logger.info("All wells set to zero heat")
            except Exception as exc:
                self.logger.error(f"Failed to zero annealer wells: {exc}")

            try:
                self.db.update_result_run(self.result_run)
            except Exception as exc:
                self.logger.error(f"Failed to persist temperature run status: {exc}")

            self.logger.info(
                f"Temperature thread exited with status: {self.result_run.status}"
            )

    def _stop_requested(self):
        return self.stop_event is not None and self.stop_event.is_set()

    def _raise_if_stopped(self):
        if self._stop_requested():
            raise RunStopped()

    def _notify_error(self, source, exc):
        if self.stop_event is not None:
            self.stop_event.set()
        if callable(self.error_callback):
            try:
                self.error_callback(source, str(exc))
            except Exception:
                pass
