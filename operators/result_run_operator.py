from datetime import datetime
from pathlib import Path
from time import sleep, monotonic
import random

from hardware import *
from models import Experiment, Sample, ImageSet, ResultRun, Image
from services import Logger, AppConfig, Movie2Tiff


class RunStopped(Exception):
    pass


class ResultRunOperator:
    def __init__(self, experiment, result_set, temperature_profile, db, stop_event=None, error_callback=None):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.result_set = result_set
        self.experiment = experiment
        self.temperature_profile = temperature_profile
        self.stop_event = stop_event
        self.error_callback = error_callback

        self.plate = self.db.get_plate_by_id(self.experiment.plate_id)
        self.image_set = self.db.get_image_set_by_id(self.result_set.image_set_id)
        self.converter = Movie2Tiff()

        self.assumed_temperature = float(self.app_config.get("assumed_temperature_celsius", 25.0))
        self.number_of_sites = self.image_set.number_of_sites or 1
        self.stack_size = self.image_set.stack_size or 1
        self.stack_step_size = self.image_set.stack_step_size or 0
        self.focus_clearance = float(self.app_config.get("focus_clearance_um", 100))
        self.autofocus_retry_interval = float(self.app_config.get("autofocus_retry_interval_seconds", 2))
        self.use_autofocus = bool(getattr(self.image_set, "autofocus", False))
        self.autofocus_margin = float(self.app_config.get("autofocus_margin", 40))
        self.autofocus_step = float(self.app_config.get("autofocus_step", 20))
        self.autofocus_tries = max(1, int(self.app_config.get("autofocus_tries", 5)))
        self.autofocus_recovery_max_attempts = max(1, int(self.app_config.get("autofocus_recovery_max_attempts", 20)))
        self.soak_wait_log_interval = float(self.app_config.get("soak_wait_log_interval_seconds", 60))
        self.soak_wait_timeout_factor = float(self.app_config.get("soak_wait_timeout_factor", 3.0))
        self.soak_wait_timeout_min_seconds = float(self.app_config.get("soak_wait_timeout_min_seconds", 900))

        camera_type = self.app_config.get("camera_type", "default_camera")
        self.camera_controller = CameraControllerFactory.create_camera_controller(camera_type)
        self.stage_controller = StageControllerFactory.create_stage_controller()
        self.illumination_controller = IlluminationControllerFactory.create_illumination_controller()
        self.focus_controller = FocusControllerFactory.create_focus_controller()

        self.channel_1_number = self.image_set.channel_1_number if self.image_set.channel_1_number is not None else 2
        self.channel_1_intensity = self.image_set.channel_1_intensity or 1.0
        self.channel_1_bitmask = self._as_hex_bitmask(self.image_set.channel_1_bitmask, "0x04")

        self.channel_2_number = self.image_set.channel_2_number
        self.channel_2_intensity = self.image_set.channel_2_intensity or 1.0
        self.channel_2_bitmask = self._as_hex_bitmask(self.image_set.channel_2_bitmask, "0x40")

        self.active_channels = [
            {
                "number": self.channel_1_number,
                "intensity": self.channel_1_intensity,
                "bitmask": self.channel_1_bitmask,
            }
        ]
        if self.channel_2_number is not None:
            self.active_channels.append(
                {
                    "number": self.channel_2_number,
                    "intensity": self.channel_2_intensity,
                    "bitmask": self.channel_2_bitmask,
                }
            )

        for channel in self.active_channels:
            self.illumination_controller.illumination_setup(channel["number"], channel["intensity"])

        self.camera_controller.set_exposure_time(self.app_config.get("exposure_time", 200000))
        self.movie_path = self.app_config.get("movie_file_directory", "./")
        self.image_path = self.app_config.get("image_file_directory", "./")

        if not self._ensure_output_dirs():
            raise RuntimeError("Output directories not writable; aborting result run setup")

        number_prev_runs_of_exp_set = self.db.get_number_result_runs_by_exp_and_set(self.experiment.id, self.result_set.id)

        kp = self.app_config.get("kp")
        ki = self.app_config.get("ki")
        kd = self.app_config.get("kd")

        self.result_run_id = self.db.add_result_run(ResultRun(
            experiment_id=self.experiment.id,
            result_set_id=self.result_set.id,
            description=(f"{self.experiment.description}: Result Run: {number_prev_runs_of_exp_set + 1}"),
            notes=(f"Result Set: {self.image_set.description}"),
            start_date_time=datetime.now(),
            status="Running",
            number_of_samples=len(self.experiment.sample),
            pid_kp=kp,
            pid_ki=ki,
            pid_kd=kd,
        ))

        self.time_at_temperature = {}
        self.actual_temperature = {}
        self.target_temperature = {}
        self.shared_lock = None

        self.result_run = self.db.get_result_run_by_id(self.result_run_id)
        self.focus_position = None
        self.sample_focus_positions = {}

        for sample in self.experiment.sample:
            sample_target = (
                self.temperature_profile.start_temp
                if self.temperature_profile is not None
                else self.assumed_temperature
            )
            self.time_at_temperature[sample.id] = 0
            self.target_temperature[sample.id] = sample_target
            self.actual_temperature[sample.id] = sample_target

    def request_stop(self, reason="Run stop requested"):
        self.logger.warning(reason)
        if self.stop_event is not None:
            self.stop_event.set()

    def run(self):
        try:
            if not self.experiment.sample:
                raise RuntimeError("Experiment has no samples to image")

            self.logger.info("Camera trigger enabled")
            self.camera_controller.set_trigger()

            self.focus_position = self.focus_controller.get_z()
            if self.use_autofocus:
                self.logger.info("Autofocus mode enabled for this run.")
            else:
                self.focus_controller.autofocus(False)
                self.focus_controller.move_z(self.focus_position - self.focus_clearance)

            if self.temperature_profile is None:
                self.logger.info(
                    "No temperature profile attached to result set; imaging samples sequentially with assumed stable temperature."
                )
                for sample in self.experiment.sample:
                    self._raise_if_stopped()
                    self._capture_sample(sample)
                self.result_run.status = "Complete"
                return

            while self.result_run.status == "Running":
                self._raise_if_stopped()

                for sample in self.experiment.sample:
                    self._raise_if_stopped()
                    self._wait_for_soak(sample.id)
                    target_temp = self.target_temperature.get(sample.id, self.assumed_temperature)
                    self.logger.info(
                        f"Soak time reached for sample {sample.id} at target {target_temp:.2f} C. Proceeding to image."
                    )
                    self._capture_sample(sample)

                    if self.shared_lock is None:
                        self.target_temperature[sample.id] += self.temperature_profile.step_size
                        self.time_at_temperature[sample.id] = 0
                    else:
                        with self.shared_lock:
                            self.target_temperature[sample.id] += self.temperature_profile.step_size
                            self.time_at_temperature[sample.id] = 0

                self.result_run.status = "Running" if self._has_remaining_temperature_steps() else "Complete"

        except RunStopped:
            if self.result_run.status in {"Running", "Paused"}:
                self.result_run.status = "Aborted"
            self.logger.warning("Imaging run stopped.")

        except Exception as exc:
            self.result_run.status = "Failed"
            self.logger.error(f"Imaging run failed: {exc}")
            self._notify_error("imaging", exc)

        finally:
            self.result_run.finish_date_time = datetime.now()
            try:
                self.db.update_result_run(self.result_run)
            except Exception as exc:
                self.logger.error(f"Failed to persist imaging run status: {exc}")

            try:
                self.illumination_controller.illumination_enable(0x00, hex_mode=True)
            except Exception as exc:
                self.logger.error(f"Failed to switch off illumination: {exc}")

            try:
                self.camera_controller.stop_recording()
            except Exception:
                pass

            self.logger.info(f"Imaging thread exited with status: {self.result_run.status}")

    def _wait_for_soak(self, sample_id):
        if self.shared_lock is None:
            return

        soak_target_seconds = float(self.temperature_profile.soak_time_seconds)
        wait_started = monotonic()
        wait_timeout = max(
            self.soak_wait_timeout_min_seconds,
            soak_target_seconds * self.soak_wait_timeout_factor,
        )
        next_progress_log = self.soak_wait_log_interval

        with self.shared_lock:
            current_time_at_temp = self.time_at_temperature.get(sample_id, 0)

        while current_time_at_temp < soak_target_seconds:
            self._raise_if_stopped()
            elapsed = monotonic() - wait_started
            if elapsed >= wait_timeout:
                raise RuntimeError(
                    f"Soak wait timed out for sample {sample_id}: "
                    f"elapsed {elapsed:.0f}s, at temperature {current_time_at_temp}s/{soak_target_seconds:.0f}s."
                )

            if elapsed >= next_progress_log:
                with self.shared_lock:
                    target_temp = self.target_temperature.get(sample_id, self.assumed_temperature)
                    actual_temp = self.actual_temperature.get(sample_id, self.assumed_temperature)
                self.logger.info(
                    f"Waiting for soak on sample {sample_id}: {current_time_at_temp}/{soak_target_seconds:.0f}s, "
                    f"elapsed {elapsed:.0f}s, target {target_temp:.2f} C, actual {actual_temp:.2f} C."
                )
                next_progress_log += self.soak_wait_log_interval

            sleep(1)
            with self.shared_lock:
                current_time_at_temp = self.time_at_temperature.get(sample_id, 0)

    def _has_remaining_temperature_steps(self):
        for sample in self.experiment.sample:
            if self.shared_lock is None:
                target_temp = self.target_temperature[sample.id]
            else:
                with self.shared_lock:
                    target_temp = self.target_temperature[sample.id]

            if self.temperature_profile.step_size > 0 and target_temp <= self.temperature_profile.end_temp:
                return True
            if self.temperature_profile.step_size < 0 and target_temp >= self.temperature_profile.end_temp:
                return True
        return False

    def _capture_sample(self, sample):
        integer_temperature = int(self.target_temperature[sample.id])
        last_site_z_height = None

        for site_number in range(self.number_of_sites):
            self._raise_if_stopped()

            movie_stub = f"{self.movie_path}/{self.result_run.id}_{sample.well_row}_{sample.well_column}_{integer_temperature}_{site_number}"
            image_stub = f"{self.image_path}/{self.result_run.id}_{sample.well_row}_{sample.well_column}_{integer_temperature}_{site_number}"
            self.camera_controller.set_filename(movie_stub)

            self._move_stage_to_site(sample, site_number)

            site_focus_z = self.focus_position
            if self.use_autofocus:
                site_focus_z = self.sample_focus_positions.get(sample.id, self.focus_position)
            else:
                site_focus_z = self.plate.get_well_z_height(sample.well_row, sample.well_column)
                if site_focus_z is None:
                    site_focus_z = self.focus_controller.get_z()

                temp_c, _ = self._read_sample_runtime(sample.id)
                site_focus_z += int(temp_c - 27) * 5
                self._readjust_focus(site_focus_z)

            if site_focus_z is not None:
                last_site_z_height = site_focus_z

            self._take_stack(sample, site_number)

            movie_filename = f"{movie_stub}{self.app_config.get('movie_extension', '.movie')}"
            self._process_stack(movie_filename, image_stub, sample, site_number)

            if site_focus_z is not None:
                self.focus_controller.move_z(site_focus_z)

        if last_site_z_height is not None:
            self.focus_controller.move_z(last_site_z_height - self.focus_clearance)

    def _move_stage_to_site(self, sample, site_number):
        row_index = ord(sample.well_row.upper()) - ord('A')
        col_index = sample.well_column - 1
        x = self.plate.centre_first_well_offset_x + (col_index * self.plate.well_spacing_x)
        y = self.plate.centre_first_well_offset_y + (row_index * self.plate.well_spacing_y)

        random_offset_x = self.plate.well_dimension * random.uniform(-0.03, 0.03)
        random_offset_y = self.plate.well_dimension * random.uniform(-0.03, 0.03)
        x = x + (random_offset_x if site_number > 0 else 0)
        y = y + (random_offset_y if site_number > 0 else 0)

        if self.use_autofocus:
            self._prepare_for_stage_move()

        self.stage_controller.move(position=x, axis="x", speed="normal")
        self.stage_controller.move(position=y, axis="y", speed="normal")
        sleep(1)

        if self.use_autofocus:
            self._reacquire_focus_after_stage_move(sample, site_number)

    def _take_stack(self, sample, site_number):
        self.logger.info(
            f"Taking image stack for sample {sample.id} at well ({sample.well_row}, {sample.well_column}), site {site_number}"
        )
        self.camera_controller.start_recording()
        for _ in range(self.stack_size):
            self._raise_if_stopped()
            new_z = self.focus_controller.get_z() + self.stack_step_size
            self.focus_controller.move_z(new_z, speed="normal")
            for channel in self.active_channels:
                self.illumination_controller.illumination_enable(channel["bitmask"], hex_mode=True)
                self.camera_controller.capture_image()
        self.camera_controller.stop_recording()

    def _readjust_focus(self, stored_z_height=None):
        if stored_z_height is not None:
            self.focus_controller.move_z(stored_z_height)
            self.focus_position = stored_z_height
            return

        if self.focus_controller.autofocus(True):
            self.focus_controller.autofocus(False)
            self.focus_position = self.focus_controller.get_z()

    def _process_stack(self, movie_filename, image_stub, sample, site_number):
        self.logger.info(f"Processing image stack {movie_filename} at site number {site_number} for sample {sample.id}")
        filenames, focus_scores = self.converter.convert(movie_name=movie_filename, file_stub=image_stub)
        channel_count = max(1, len(self.active_channels))

        for idx, (file, score) in enumerate(zip(filenames, focus_scores)):
            file_path = Path(str(file)).name

            sample_temp, sample_time = self._read_sample_runtime(sample.id)
            channel = self.active_channels[idx % channel_count]

            new_image = Image(
                sample_id=sample.id,
                result_run_id=self.result_run.id,
                site_number=site_number,
                stack_number=idx,
                led_number=channel["number"],
                dimension_x=getattr(self.camera_controller, "image_dimension_x", 0),
                dimension_y=getattr(self.camera_controller, "image_dimension_y", 0),
                file_path=file_path,
                timestamp=datetime.now(),
                temperature=sample_temp,
                time_at_temperature=sample_time,
                focus_score=score,
                average_droplet_size=0.0,
                standard_deviation_droplet_size=0.0,
            )
            self.db.add_result_run_image(new_image)

        self.logger.info(f"Image stack extracted for movie {movie_filename}")

    def _read_sample_runtime(self, sample_id):
        if self.shared_lock is None:
            return (
                self.actual_temperature.get(sample_id, self.assumed_temperature),
                self.time_at_temperature.get(sample_id, 0),
            )

        with self.shared_lock:
            return (
                self.actual_temperature.get(sample_id, self.assumed_temperature),
                self.time_at_temperature.get(sample_id, 0),
            )

    def _ensure_output_dirs(self) -> bool:
        for path in (self.movie_path, self.image_path):
            p = Path(path).expanduser()
            try:
                p.mkdir(parents=True, exist_ok=True)
                test_file = p / ".write_test"
                test_file.write_text("ok")
                test_file.unlink(missing_ok=True)
            except Exception as exc:
                self.logger.error(f"Output path not writable: {p} ({exc})")
                return False
        return True

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

    def _notify_pause(self, source, message):
        if callable(self.error_callback):
            try:
                self.error_callback(source, str(message))
            except Exception:
                pass

    def _set_result_run_status(self, status):
        if self.result_run.status == status:
            return
        self.result_run.status = status
        try:
            self.db.update_result_run(self.result_run)
        except Exception as exc:
            self.logger.error(f"Failed to persist run status '{status}': {exc}")

    def _prepare_for_stage_move(self):
        if self.focus_position is None:
            self.focus_position = self.focus_controller.get_z()
        self.focus_controller.autofocus(False)
        self.focus_controller.move_z(self.focus_position - self.focus_clearance)

    def _reacquire_focus_after_stage_move(self, sample, site_number):
        if self._attempt_autofocus_lock(sample, site_number):
            return

        self._pause_for_autofocus_recovery(
            f"Autofocus timed out after {self.autofocus_tries} tries at sample {sample.id}, site {site_number}. "
            "Run paused for manual intervention.",
            sample,
            site_number,
        )

    def _get_autofocus_baseline(self, sample):
        sample_focus = self.sample_focus_positions.get(sample.id)
        if sample_focus is not None:
            return sample_focus

        plate_focus = self.plate.get_well_z_height(sample.well_row, sample.well_column)
        if plate_focus is not None:
            return plate_focus

        if self.focus_position is not None:
            return self.focus_position

        return self.focus_controller.get_z()

    def _attempt_autofocus_lock(self, sample, site_number):
        baseline_z = self._get_autofocus_baseline(sample)
        start_z = baseline_z - self.autofocus_margin

        for attempt in range(self.autofocus_tries):
            self._raise_if_stopped()
            target_z = start_z + (attempt * self.autofocus_step)
            self.focus_controller.autofocus(False)
            self.focus_controller.move_z(target_z)

            if self.focus_controller.autofocus(True):
                locked_z = self.focus_controller.get_z()
                self.focus_controller.autofocus(False)
                self.focus_controller.move_z(locked_z)
                self.focus_position = locked_z
                self.sample_focus_positions[sample.id] = locked_z
                sample.autofocus_z = locked_z
                self.logger.info(
                    f"Autofocus locked at sample {sample.id}, site {site_number}, z={locked_z:.2f}, "
                    f"try {attempt + 1}/{self.autofocus_tries}."
                )
                return True

            self.focus_controller.autofocus(False)
            self.logger.warning(
                f"Autofocus try {attempt + 1}/{self.autofocus_tries} failed for sample {sample.id}, "
                f"site {site_number}, target z={target_z:.2f}."
            )

        return False

    def _pause_for_autofocus_recovery(self, reason, sample, site_number):
        self.logger.error(reason)
        self._set_result_run_status("Paused")
        self._notify_pause("autofocus_pause", reason)

        recovery_attempts = 0
        recovery_started = monotonic()
        while True:
            self._raise_if_stopped()
            if callable(self.error_callback):
                sleep(self.autofocus_retry_interval)
            else:
                input("Autofocus timed out. Adjust focus and press Enter to retry autofocus search.")

            recovery_attempts += 1
            if self._attempt_autofocus_lock(sample, site_number):
                self._set_result_run_status("Running")
                self.logger.info("Autofocus recovered. Resuming run.")
                return

            elapsed = monotonic() - recovery_started
            if recovery_attempts >= self.autofocus_recovery_max_attempts:
                raise RuntimeError(
                    f"Autofocus recovery exceeded {self.autofocus_recovery_max_attempts} attempts "
                    f"for sample {sample.id}, site {site_number} after {elapsed:.0f}s."
                )

            self.logger.warning(
                f"Autofocus still not locked after recovery attempt {recovery_attempts} "
                f"for sample {sample.id}, site {site_number} (elapsed {elapsed:.0f}s)."
            )

    @staticmethod
    def _as_hex_bitmask(bitmask_value, fallback):
        if bitmask_value is None:
            return fallback
        if isinstance(bitmask_value, int):
            return hex(bitmask_value)
        candidate = str(bitmask_value).strip()
        if not candidate:
            return fallback
        if candidate.lower().startswith("0x"):
            return candidate
        if all(ch in "01" for ch in candidate):
            return hex(int(candidate, 2))
        return candidate
