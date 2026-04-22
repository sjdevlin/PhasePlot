from datetime import datetime
from pathlib import Path
from threading import Event
from time import sleep, monotonic
import math
from PIL import Image as PILImage

from hardware import *
from models import Experiment, Sample, ImageSet, ResultRun, Image
from services import Logger, AppConfig, Movie2Tiff


class RunStopped(Exception):
    pass


class ResultRunOperator:
    def __init__(
        self,
        experiment,
        result_set,
        temperature_profile,
        db,
        stop_event=None,
        error_callback=None,
        manual_site_callback=None,
    ):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.result_set = result_set
        self.experiment = experiment
        self.temperature_profile = temperature_profile
        self.temperature_step = 0.0
        self.stop_event = stop_event
        self.error_callback = error_callback
        self.manual_site_callback = manual_site_callback

        if self.temperature_profile is not None:
            self.temperature_step = self._resolve_temperature_step()

        self.plate = self.db.get_plate_by_id(self.experiment.plate_id)
        self.image_set = self.db.get_image_set_by_id(self.result_set.image_set_id)
        self.converter = Movie2Tiff(
            compression=self.app_config.get("movie2tiff_compression", "tiff_lzw"),
            downsample=bool(self.app_config.get("movie2tiff_downsample", True)),
            convert_8bit=bool(self.app_config.get("movie2tiff_convert_8bit", False)),
            output_format=str(self.app_config.get("movie2tiff_output_format", "png")),
        )

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
        self.temperature_stall_timeout_seconds = float(
            self.app_config.get("temperature_stall_timeout_seconds", 60)
        )

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
        self.has_second_channel = self.channel_2_number is not None

        self.active_channels = [
            {
                "number": self.channel_1_number,
                "intensity": self.channel_1_intensity,
                "bitmask": self.channel_1_bitmask,
            }
        ]
        if self.has_second_channel:
            self.active_channels.append(
                {
                    "number": self.channel_2_number,
                    "intensity": self.channel_2_intensity,
                    "bitmask": self.channel_2_bitmask,
                }
            )

        for channel in self.active_channels:
            self.illumination_controller.illumination_setup(channel["number"], channel["intensity"])

        self.imaging_exposure_time = self.app_config.get("exposure_time", 200000)
        self.manual_site_exposure_time = 150000
        self.camera_controller.set_exposure_time(self.imaging_exposure_time)
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
        self.temperature_last_update = {}
        self.shared_lock = None

        self.result_run = self.db.get_result_run_by_id(self.result_run_id)
        self.focus_position = None
        self.sample_focus_positions = {}
        self.manual_pause_event = Event()
        self.manual_pause_active = False
        self.autofocus_pause_active = False
        self.site_offsets = self._build_site_offsets()
        self.manual_sites_calibrated = False
        self.sample_site_positions = {}
        self.current_capture_sample = None
        self.current_capture_site_number = None

        for sample in self.experiment.sample:
            sample_target = (
                self.temperature_profile.start_temp
                if self.temperature_profile is not None
                else self.assumed_temperature
            )
            self.time_at_temperature[sample.id] = 0
            self.target_temperature[sample.id] = sample_target
            self.actual_temperature[sample.id] = sample_target
            self.temperature_last_update[sample.id] = monotonic()

    def request_stop(self, reason="Run stop requested"):
        self.logger.warning(reason)
        if self.stop_event is not None:
            self.stop_event.set()

    def request_pause(self, reason="Run pause requested"):
        self.logger.warning(reason)
        self.manual_pause_active = True
        self.manual_pause_event.set()
        self._set_result_run_status("Paused")

    def request_resume(self, reason="Run resume requested"):
        self.logger.warning(reason)
        self.manual_pause_event.clear()

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
                self._select_manual_sites()
                for sample in self.experiment.sample:
                    self._raise_if_stopped()
                    self._capture_sample(sample)
                self.result_run.status = "Complete"
                return

            while self.result_run.status in {"Running", "Paused"}:
                self._raise_if_stopped()
                self._wait_if_paused()
                if self.result_run.status != "Running":
                    sleep(0.2)
                    continue

                target_temp = self._current_target_temperature()
                self._select_manual_sites()
                self.logger.info(
                    f"Waiting for all wells to soak at shared target {target_temp:.2f} C before imaging."
                )
                self._wait_for_all_samples_soak()
                self.logger.info(
                    f"All wells reached soak time at shared target {target_temp:.2f} C. Imaging all samples."
                )

                for sample in self.experiment.sample:
                    self._raise_if_stopped()
                    self._wait_if_paused()
                    self.logger.info(
                        f"Imaging sample {sample.id} at shared target {target_temp:.2f} C."
                    )
                    self._capture_sample(sample)

                if self._is_final_temperature(target_temp):
                    self.result_run.status = "Complete"
                else:
                    next_target = self._next_target_temperature(target_temp)
                    self._set_all_target_temperatures(next_target)
                    self.logger.info(
                        f"Completed imaging all samples at {target_temp:.2f} C. "
                        f"Advancing all wells to shared target {next_target:.2f} C."
                    )

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
        while True:
            self._raise_if_stopped()
            self._wait_if_paused()

            with self.shared_lock:
                current_time_at_temp = self.time_at_temperature.get(sample_id, 0)
                target_temp = self.target_temperature.get(sample_id, self.assumed_temperature)
                actual_temp = self.actual_temperature.get(sample_id, self.assumed_temperature)
                last_temp_update = self.temperature_last_update.get(sample_id)

            if current_time_at_temp >= soak_target_seconds:
                return

            elapsed = monotonic() - wait_started
            if last_temp_update is not None:
                stalled_for = max(0.0, monotonic() - float(last_temp_update))
                if stalled_for >= self.temperature_stall_timeout_seconds:
                    raise RuntimeError(
                        f"Temperature updates stalled for sample {sample_id}: "
                        f"no update for {stalled_for:.0f}s while waiting for soak "
                        f"({current_time_at_temp}s/{soak_target_seconds:.0f}s)."
                    )

            # Timeout is based on time spent not soaking, not total wait wall time.
            non_soak_elapsed = max(0.0, elapsed - float(current_time_at_temp))

            if non_soak_elapsed >= wait_timeout:
                raise RuntimeError(
                    f"Soak wait timed out for sample {sample_id}: "
                    f"elapsed {elapsed:.0f}s, at temperature {current_time_at_temp}s/{soak_target_seconds:.0f}s, "
                    f"non-soak elapsed {non_soak_elapsed:.0f}s."
                )

            if elapsed >= next_progress_log:
                self.logger.info(
                    f"Waiting for soak on sample {sample_id}: {current_time_at_temp}/{soak_target_seconds:.0f}s, "
                    f"elapsed {elapsed:.0f}s, non-soak elapsed {non_soak_elapsed:.0f}s, "
                    f"target {target_temp:.2f} C, actual {actual_temp:.2f} C."
                )
                next_progress_log += self.soak_wait_log_interval

            sleep(1)

    def _select_manual_sites(self):
        if self.manual_sites_calibrated:
            return

        if self.manual_site_callback is None:
            raise RuntimeError("Manual site selection is required, but no UI callback is configured.")

        self.logger.info("Starting manual site selection for this imaging run.")
        self._configure_camera_for_manual_site_selection()
        for sample in self.experiment.sample:
            self._raise_if_stopped()
            self._wait_if_paused()

            self._move_stage_to_well_center(sample)

            for site_number in range(self.number_of_sites):
                self._raise_if_stopped()
                self._wait_if_paused()

                self.logger.info(
                    f"Waiting for manual site selection for sample {sample.id}, "
                    f"well {sample.well_row}{sample.well_column}, site {site_number + 1}/{self.number_of_sites}."
                )
                self.manual_site_callback(sample, site_number, self.number_of_sites)

                x = self._read_stage_position("x")
                y = self._read_stage_position("y")
                z = float(self.focus_controller.get_z())
                autofocus_offset = float(self.focus_controller.get_autofocus_offset())
                self.sample_site_positions[(sample.id, site_number)] = {
                    "x": x,
                    "y": y,
                    "autofocus_offset": autofocus_offset,
                }
                self._update_plate_well_z_height(sample, z)
                self.logger.info(
                    f"Stored manual site for sample {sample.id}, site {site_number}: "
                    f"x={x:.3f}, y={y:.3f}, z={z:.2f}, autofocus_offset={autofocus_offset:.2f}."
                )

        self.manual_sites_calibrated = True
        self._configure_camera_for_imaging()
        self.logger.info("Manual site selection complete. Continuing imaging run.")

    def _configure_camera_for_manual_site_selection(self):
        if hasattr(self.camera_controller, "set_trigger_off"):
            self.camera_controller.set_trigger_off()
        else:
            self.logger.warning("Camera controller does not support trigger-off mode for manual site selection.")
        self.camera_controller.set_exposure_time(self.manual_site_exposure_time)
        self.logger.info(
            f"Camera configured for manual site selection: trigger off, exposure {self.manual_site_exposure_time}."
        )

    def _configure_camera_for_imaging(self):
        self.camera_controller.set_exposure_time(self.imaging_exposure_time)
        self.camera_controller.set_trigger()
        self.logger.info(
            f"Camera configured for imaging: trigger on, exposure {self.imaging_exposure_time}."
        )

    def _read_stage_position(self, axis):
        if hasattr(self.stage_controller, "get_position"):
            return float(self.stage_controller.get_position(axis))
        return float(self.stage_controller.get(axis))

    def _move_stage_to_well_center(self, sample):
        x, y = self._get_well_center_position(sample)
        if self.use_autofocus:
            self._prepare_for_stage_move()

        self.stage_controller.move(position=x, axis="x", speed="normal")
        self.stage_controller.move(position=y, axis="y", speed="normal")
        sleep(1)

    def _get_well_center_position(self, sample):
        row_index = ord(sample.well_row.upper()) - ord('A')
        col_index = sample.well_column - 1
        x = self.plate.centre_first_well_offset_x + (col_index * self.plate.well_spacing_x)
        y = self.plate.centre_first_well_offset_y + (row_index * self.plate.well_spacing_y)
        return x, y

    def _update_plate_well_z_height(self, sample, z_height):
        for well in self.plate.well:
            if well.well_row == sample.well_row and well.well_column == sample.well_column:
                well.z_height = float(z_height)
                self.db.update_plate(self.plate)
                self.logger.info(
                    f"Updated plate well {sample.well_row}{sample.well_column} z height to {float(z_height):.2f}."
                )
                return

        self.logger.warning(
            f"Could not update z height: no plate well found for {sample.well_row}{sample.well_column}."
        )

    def _wait_for_all_samples_soak(self):
        if self.shared_lock is None:
            return

        soak_target_seconds = float(self.temperature_profile.soak_time_seconds)
        wait_started = monotonic()
        wait_timeout = max(
            self.soak_wait_timeout_min_seconds,
            soak_target_seconds * self.soak_wait_timeout_factor,
        )
        next_progress_log = self.soak_wait_log_interval

        while True:
            self._raise_if_stopped()
            self._wait_if_paused()

            with self.shared_lock:
                sample_states = [
                    (
                        sample.id,
                        self.time_at_temperature.get(sample.id, 0),
                        self.target_temperature.get(sample.id, self.assumed_temperature),
                        self.actual_temperature.get(sample.id, self.assumed_temperature),
                        self.temperature_last_update.get(sample.id),
                    )
                    for sample in self.experiment.sample
                ]

            if all(time_at_temp >= soak_target_seconds for _, time_at_temp, _, _, _ in sample_states):
                return

            elapsed = monotonic() - wait_started
            min_time_at_temp = min((time_at_temp for _, time_at_temp, _, _, _ in sample_states), default=0)

            stalled_samples = []
            for sample_id, current_time_at_temp, _, _, last_temp_update in sample_states:
                if current_time_at_temp >= soak_target_seconds or last_temp_update is None:
                    continue
                stalled_for = max(0.0, monotonic() - float(last_temp_update))
                if stalled_for >= self.temperature_stall_timeout_seconds:
                    stalled_samples.append((sample_id, stalled_for, current_time_at_temp))

            if stalled_samples:
                sample_id, stalled_for, current_time_at_temp = stalled_samples[0]
                raise RuntimeError(
                    f"Temperature updates stalled for sample {sample_id}: "
                    f"no update for {stalled_for:.0f}s while waiting for all wells to soak "
                    f"({current_time_at_temp}s/{soak_target_seconds:.0f}s)."
                )

            non_soak_elapsed = max(0.0, elapsed - float(min_time_at_temp))
            if non_soak_elapsed >= wait_timeout:
                slowest_sample = min(sample_states, key=lambda state: state[1])
                sample_id, current_time_at_temp, target_temp, actual_temp, _ = slowest_sample
                raise RuntimeError(
                    f"Soak wait timed out before all wells were ready: "
                    f"slowest sample {sample_id} at {current_time_at_temp}s/{soak_target_seconds:.0f}s, "
                    f"target {target_temp:.2f} C, actual {actual_temp:.2f} C, "
                    f"elapsed {elapsed:.0f}s, non-soak elapsed {non_soak_elapsed:.0f}s."
                )

            if elapsed >= next_progress_log:
                slowest_sample = min(sample_states, key=lambda state: state[1])
                sample_id, current_time_at_temp, target_temp, actual_temp, _ = slowest_sample
                self.logger.info(
                    f"Waiting for all wells to soak: slowest sample {sample_id} "
                    f"{current_time_at_temp}/{soak_target_seconds:.0f}s, "
                    f"elapsed {elapsed:.0f}s, non-soak elapsed {non_soak_elapsed:.0f}s, "
                    f"target {target_temp:.2f} C, actual {actual_temp:.2f} C."
                )
                next_progress_log += self.soak_wait_log_interval

            sleep(1)

    def _current_target_temperature(self):
        if not self.experiment.sample:
            return self.assumed_temperature

        sample_id = self.experiment.sample[0].id
        if self.shared_lock is None:
            return float(self.target_temperature.get(sample_id, self.assumed_temperature))

        with self.shared_lock:
            return float(self.target_temperature.get(sample_id, self.assumed_temperature))

    def _set_all_target_temperatures(self, target_temperature):
        target_temperature = float(target_temperature)
        if self.shared_lock is None:
            for sample in self.experiment.sample:
                self.target_temperature[sample.id] = target_temperature
                self.time_at_temperature[sample.id] = 0
            return

        with self.shared_lock:
            for sample in self.experiment.sample:
                self.target_temperature[sample.id] = target_temperature
                self.time_at_temperature[sample.id] = 0

    def _is_final_temperature(self, target_temperature):
        if self.temperature_profile is None:
            return True

        epsilon = 1e-6
        end_temp = float(self.temperature_profile.end_temp)
        if abs(self.temperature_step) <= epsilon:
            return True
        if self.temperature_step > 0:
            return target_temperature >= (end_temp - epsilon)
        return target_temperature <= (end_temp + epsilon)

    def _next_target_temperature(self, target_temperature):
        next_target = float(target_temperature) + self.temperature_step
        end_temp = float(self.temperature_profile.end_temp)

        if self.temperature_step > 0 and next_target > end_temp:
            return end_temp
        if self.temperature_step < 0 and next_target < end_temp:
            return end_temp
        return next_target

    def _get_sample_target_temperature(self, sample_id):
        if self.shared_lock is None:
            return float(self.target_temperature.get(sample_id, self.assumed_temperature))

        with self.shared_lock:
            return float(self.target_temperature.get(sample_id, self.assumed_temperature))

    def _capture_sample(self, sample):
        target_temperature = self._get_sample_target_temperature(sample.id)
        temperature_tag = f"{target_temperature:.2f}".replace(".", "p")
        last_site_z_height = None

        for site_number in range(self.number_of_sites):
            self._raise_if_stopped()
            self._wait_if_paused()
            self.current_capture_sample = sample
            self.current_capture_site_number = site_number

            movie_stub = f"{self.movie_path}/{self.result_run.id}_{sample.well_row}_{sample.well_column}_{temperature_tag}_{site_number}"
            image_stub = f"{self.image_path}/{self.result_run.id}_{sample.well_row}_{sample.well_column}_{temperature_tag}_{site_number}"
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
        self.current_capture_sample = None
        self.current_capture_site_number = None

    def _move_stage_to_site(self, sample, site_number):
        stored_site = self.sample_site_positions.get((sample.id, site_number))
        if stored_site is not None:
            x = stored_site["x"]
            y = stored_site["y"]
        else:
            x, y = self._get_well_center_position(sample)

        if stored_site is None and site_number < len(self.site_offsets):
            offset_x, offset_y = self.site_offsets[site_number]
        else:
            offset_x, offset_y = (0.0, 0.0)
        x += offset_x
        y += offset_y

        if self.use_autofocus:
            self._prepare_for_stage_move()

        if stored_site is not None:
            self._apply_autofocus_offset(sample, site_number)

        self.stage_controller.move(position=x, axis="x", speed="normal")
        self.stage_controller.move(position=y, axis="y", speed="normal")
        sleep(1)

        if self.use_autofocus:
            self._reacquire_focus_after_stage_move(sample, site_number)

    def _take_stack(self, sample, site_number):
        self._configure_camera_for_imaging()
        self.logger.info(
            f"Taking image stack for sample {sample.id} at well ({sample.well_row}, {sample.well_column}), site {site_number}"
        )
        self.camera_controller.start_recording()
        for _ in range(self.stack_size):
            self._raise_if_stopped()
            self._wait_if_paused()
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
            dimension_x, dimension_y = self._resolve_saved_image_dimensions(Path(str(file)))

            sample_temp, sample_time = self._read_sample_runtime(sample.id)
            channel = self.active_channels[idx % channel_count]
            z_stack_number = idx // channel_count

            new_image = Image(
                sample_id=sample.id,
                result_run_id=self.result_run.id,
                site_number=site_number,
                stack_number=z_stack_number,
                led_number=channel["number"],
                dimension_x=dimension_x,
                dimension_y=dimension_y,
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

    def _resolve_saved_image_dimensions(self, image_path: Path):
        fallback_x = int(getattr(self.camera_controller, "image_dimension_x", 0) or 0)
        fallback_y = int(getattr(self.camera_controller, "image_dimension_y", 0) or 0)
        try:
            with PILImage.open(image_path) as img:
                width, height = img.size
                return int(width), int(height)
        except Exception:
            return fallback_x, fallback_y

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

    def _wait_if_paused(self):
        if not self.manual_pause_event.is_set():
            return
        self.logger.info("Run paused by user. Waiting for resume.")
        while self.manual_pause_event.is_set():
            self._raise_if_stopped()
            sleep(0.2)
        self._refresh_current_site_autofocus_offset_after_pause()
        if self.manual_pause_active and not self.autofocus_pause_active and self.result_run.status == "Paused":
            self._set_result_run_status("Running")
        self.manual_pause_active = False
        self.logger.info("Run resumed by user.")

    def _refresh_current_site_autofocus_offset_after_pause(self):
        if not self.manual_pause_active:
            return
        if self.current_capture_sample is None or self.current_capture_site_number is None:
            return

        site_key = (self.current_capture_sample.id, self.current_capture_site_number)
        stored_site = self.sample_site_positions.get(site_key)
        if stored_site is None:
            return

        offset_at_current_temp = float(self.focus_controller.get_autofocus_offset())
        temperature_adjustment = self._temperature_autofocus_adjustment(self.current_capture_sample.id)
        base_offset = offset_at_current_temp - temperature_adjustment
        stored_site["autofocus_offset"] = base_offset
        self.logger.info(
            f"Updated stored autofocus offset for sample {self.current_capture_sample.id}, "
            f"site {self.current_capture_site_number} after pause: "
            f"stepper_a={offset_at_current_temp:.2f}, base_offset={base_offset:.2f}."
        )

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
        self._apply_autofocus_offset(sample, site_number)
        baseline_z = self._get_autofocus_baseline(sample)
        start_z = baseline_z - self.autofocus_margin

        for attempt in range(self.autofocus_tries):
            self._raise_if_stopped()
            self._wait_if_paused()
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

    def _apply_autofocus_offset(self, sample, site_number):
        stored_site = self.sample_site_positions.get((sample.id, site_number))
        if stored_site is not None:
            autofocus_offset = stored_site.get("autofocus_offset", 0.0)
        else:
            autofocus_offset = self.plate.get_well_autofocus_offset(sample.well_row, sample.well_column)
        if autofocus_offset is None:
            autofocus_offset = 0.0
        autofocus_offset = float(autofocus_offset) + self._temperature_autofocus_adjustment(sample.id)

        if not self.focus_controller.move_autofocus_offset(autofocus_offset):
            raise RuntimeError(
                f"Failed to apply autofocus offset {autofocus_offset} um at sample {sample.id}, site {site_number}."
            )

        self.logger.info(
            f"Applied autofocus offset {float(autofocus_offset):.2f} um for sample {sample.id}, site {site_number}."
        )

    def _temperature_autofocus_adjustment(self, sample_id):
        if self.temperature_profile is None:
            return 0.0

        start_temp = float(self.temperature_profile.start_temp)
        current_temp = self._get_sample_target_temperature(sample_id)
        return (current_temp - start_temp) * 20.0

    def _pause_for_autofocus_recovery(self, reason, sample, site_number):
        self.logger.error(reason)
        self.autofocus_pause_active = True
        self._set_result_run_status("Paused")
        self._notify_pause("autofocus_pause", reason)

        recovery_attempts = 0
        recovery_started = monotonic()
        while True:
            self._raise_if_stopped()
            self._wait_if_paused()
            if callable(self.error_callback):
                sleep(self.autofocus_retry_interval)
            else:
                input("Autofocus timed out. Adjust focus and press Enter to retry autofocus search.")

            recovery_attempts += 1
            if self._attempt_autofocus_lock(sample, site_number):
                self.autofocus_pause_active = False
                self._set_result_run_status("Running")
                self.logger.info("Autofocus recovered. Resuming run.")
                return

            elapsed = monotonic() - recovery_started
            if recovery_attempts >= self.autofocus_recovery_max_attempts:
                self.autofocus_pause_active = False
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

    def _resolve_temperature_step(self):
        start_temp = float(self.temperature_profile.start_temp)
        end_temp = float(self.temperature_profile.end_temp)
        raw_step = float(self.temperature_profile.step_size)
        epsilon = 1e-9

        if abs(raw_step) <= epsilon and abs(end_temp - start_temp) > epsilon:
            raise RuntimeError(
                "Temperature profile step_size cannot be zero when start_temp and end_temp differ."
            )

        if start_temp > end_temp and raw_step > 0:
            corrected_step = -abs(raw_step)
            self.logger.warning(
                f"Temperature profile step direction mismatch detected ({raw_step:+.3f} C). "
                f"Using {corrected_step:+.3f} C to ramp from {start_temp:.2f} to {end_temp:.2f}."
            )
            return corrected_step

        if start_temp < end_temp and raw_step < 0:
            corrected_step = abs(raw_step)
            self.logger.warning(
                f"Temperature profile step direction mismatch detected ({raw_step:+.3f} C). "
                f"Using {corrected_step:+.3f} C to ramp from {start_temp:.2f} to {end_temp:.2f}."
            )
            return corrected_step

        return raw_step

    def _build_site_offsets(self):
        if self.number_of_sites <= 0:
            return [(0.0, 0.0)]

        if self.number_of_sites == 1:
            offsets = [(0.0, 0.0)]
        else:
            # Stage coordinates are in mm at this level; Temika conversion to um happens in stage controller.
            site_circle_diameter_mm = 0.5
            radius_mm = site_circle_diameter_mm / 2.0
            offsets = []
            for idx in range(self.number_of_sites):
                theta = (2.0 * math.pi * idx) / float(self.number_of_sites)
                offsets.append((radius_mm * math.cos(theta), radius_mm * math.sin(theta)))

        for idx, (offset_x, offset_y) in enumerate(offsets):
            self.logger.info(
                f"Site {idx} offset set for this run: dx={offset_x:.2f}, dy={offset_y:.2f}."
            )

        return offsets
