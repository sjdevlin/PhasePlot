from services import AppConfig, Logger


class ResultRunDetailPresenter():
    def __init__(self, result_run_id, view, db):
        self.view = view
        self.db = db
        self.app_config = AppConfig()
        self.logger = Logger()

        self.view.next_sample_button.configure(command=self.next_sample)
        self.view.prev_sample_button.configure(command=self.prev_sample)
        self.view.next_stack_button.configure(command=self.next_stack)
        self.view.prev_stack_button.configure(command=self.prev_stack)
        self.view.next_site_button.configure(command=self.next_site)
        self.view.prev_site_button.configure(command=self.prev_site)
        self.view.next_temp_button.configure(command=self.next_temp)
        self.view.prev_temp_button.configure(command=self.prev_temp)
        self.view.toggle_channel_button.configure(command=self.toggle_channel)

        result_run = self.db.get_result_run_by_id(result_run_id)
        result_set = self.db.get_result_set_by_id(result_run.result_set_id) if result_run else None
        self.image_set = self.db.get_image_set_by_id(result_set.image_set_id) if result_set else None

        self.preferred_channel_order = []
        if self.image_set is not None:
            for channel_number in [self.image_set.channel_1_number, self.image_set.channel_2_number]:
                if channel_number is not None and channel_number not in self.preferred_channel_order:
                    self.preferred_channel_order.append(channel_number)

        self.images = self.db.get_images_by_result_run_id(result_run_id)
        if not self.images:
            self.logger.error(f"No images found for result run {result_run_id}.")
            return

        self.sample_id = max(img.sample_id for img in self.images)
        self.site_number = 0
        self._update_available_temperatures()
        self.temperature = self.available_temperatures[-1] if self.available_temperatures else 0

        self.channel_number = None
        self.stack_index = 0
        self._ensure_valid_selection(reset_stack=True)
        self.refresh_view()

    def _images_for_current_selection(self):
        return [
            img for img in self.images
            if img.sample_id == self.sample_id
            and img.site_number == self.site_number
            and img.temperature == self.temperature
        ]

    def _available_channels_for_selection(self):
        selection_images = sorted(self._images_for_current_selection(), key=lambda img: img.stack_number)
        detected_channels = []
        for img in selection_images:
            if img.led_number not in detected_channels:
                detected_channels.append(img.led_number)

        ordered_channels = [ch for ch in self.preferred_channel_order if ch in detected_channels]
        for channel in detected_channels:
            if channel not in ordered_channels:
                ordered_channels.append(channel)
        return ordered_channels

    def _channel_images(self, channel_number):
        return sorted(
            [img for img in self._images_for_current_selection() if img.led_number == channel_number],
            key=lambda img: img.stack_number,
        )

    def _ensure_valid_selection(self, reset_stack=False):
        self.channel_numbers = self._available_channels_for_selection()
        if not self.channel_numbers:
            self.channel_numbers = [None]

        if self.channel_number not in self.channel_numbers:
            self.channel_number = self.channel_numbers[0]
            reset_stack = True

        current_channel_images = self._channel_images(self.channel_number)
        if not current_channel_images:
            self.stack_index = 0
            return

        if reset_stack:
            self.stack_index = self._get_index_of_sharpest_image(current_channel_images)
        else:
            self.stack_index = max(0, min(self.stack_index, len(current_channel_images) - 1))

    def _update_available_temperatures(self):
        self.available_temperatures = sorted(
            list(
                {
                    img.temperature for img in self.images
                    if img.sample_id == self.sample_id and img.site_number == self.site_number
                }
            ),
            reverse=True,
        )
        if not self.available_temperatures:
            self.available_temperatures = [0]

    def _set_closest_temperature(self, target_temperature):
        if not self.available_temperatures:
            self.temperature = 0
            return
        self.temperature = min(self.available_temperatures, key=lambda t: abs(round(t) - round(target_temperature)))

    def _get_index_of_sharpest_image(self, channel_images=None):
        if channel_images is None:
            channel_images = self._channel_images(self.channel_number)

        if not channel_images:
            self.logger.warning(
                f"No stack found for sample {self.sample_id}, site {self.site_number}, temp {self.temperature}, channel {self.channel_number}."
            )
            return 0

        sharpest_idx = max(
            range(len(channel_images)),
            key=lambda idx: channel_images[idx].focus_score if channel_images[idx].focus_score is not None else -1,
        )
        return sharpest_idx

    def refresh_view(self):
        sample = self.db.get_sample_by_id(self.sample_id)
        if not sample:
            self.logger.error(f"No sample found with ID {self.sample_id}.")
            return

        experiment = self.db.get_experiment_by_id(sample.experiment_id)

        self._ensure_valid_selection()
        current_channel_images = self._channel_images(self.channel_number)
        selected_image = current_channel_images[self.stack_index] if current_channel_images else None

        channel_index = self.channel_numbers.index(self.channel_number) if self.channel_number in self.channel_numbers else 0
        channel_label = str(channel_index + 1)
        if self.channel_number is not None:
            channel_label = f"{channel_label} (#{self.channel_number})"

        self.view.update_channel_button(channel_label)
        self.view.set_channel_button_enabled(len(self.channel_numbers) > 1)

        concentration = (
            sample.ns_concentration * experiment.max_ns_concentration / 100
            if experiment and experiment.max_ns_concentration
            else 0
        )

        meta_data = f"Sample: {self.sample_id} Row: {sample.well_row}, Column: {sample.well_column}"
        meta_data += f"\nConcentration: {concentration:.2f} µM"
        meta_data += f"\nSite: {self.site_number}, Stack: {self.stack_index}"
        meta_data += f"\nChannel: {channel_label}"

        self._update_nav_buttons(current_channel_images)

        if selected_image is None:
            self.logger.warning(
                f"No image found for sample {self.sample_id}, site {self.site_number}, stack {self.stack_index}, temp {self.temperature}, channel {self.channel_number}."
            )
            return

        if selected_image.focus_score is not None:
            meta_data += f"\nFocus Score: {selected_image.focus_score:.2f}"
        else:
            meta_data += "\nFocus Score: n/a"
        meta_data += f"\nTemperature: {self.temperature}"

        try:
            image_file_path = selected_image.file_path
            base_path = self.app_config.get('image_file_directory', '')
            full_image_path = f"{base_path}/{image_file_path}" if base_path else image_file_path
            self.view.show_image(full_image_path, meta_data)
        except Exception as e:
            self.logger.error(f"Unexpected error while refreshing image view: {e}")

    def next_sample(self):
        sorted_samples = sorted({img.sample_id for img in self.images})
        current_temp = self.temperature

        try:
            self.sample_id = next(sample_id for sample_id in sorted_samples if sample_id > self.sample_id)
        except StopIteration:
            self.logger.info("No next sample available.")
            return

        self.site_number = 0
        self._update_available_temperatures()
        self._set_closest_temperature(current_temp)
        self._ensure_valid_selection(reset_stack=True)
        self.refresh_view()

    def prev_sample(self):
        sorted_samples = sorted({img.sample_id for img in self.images})
        previous_samples = [sample_id for sample_id in sorted_samples if sample_id < self.sample_id]
        if not previous_samples:
            self.logger.info("No previous sample available.")
            return

        current_temp = self.temperature
        self.sample_id = previous_samples[-1]
        self.site_number = 0
        self._update_available_temperatures()
        self._set_closest_temperature(current_temp)
        self._ensure_valid_selection(reset_stack=True)
        self.refresh_view()

    def next_site(self):
        next_site = self.site_number + 1
        if not any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == next_site):
            return

        current_temp = self.temperature
        self.site_number = next_site
        self._update_available_temperatures()
        self._set_closest_temperature(current_temp)
        self._ensure_valid_selection(reset_stack=True)
        self.refresh_view()

    def prev_site(self):
        prev_site = self.site_number - 1
        if not any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == prev_site):
            return

        current_temp = self.temperature
        self.site_number = prev_site
        self._update_available_temperatures()
        self._set_closest_temperature(current_temp)
        self._ensure_valid_selection(reset_stack=True)
        self.refresh_view()

    def next_stack(self):
        channel_images = self._channel_images(self.channel_number)
        if self.stack_index < len(channel_images) - 1:
            self.stack_index += 1
        self.refresh_view()

    def prev_stack(self):
        if self.stack_index > 0:
            self.stack_index -= 1
        self.refresh_view()

    def next_temp(self):
        try:
            current_index = self.available_temperatures.index(self.temperature)
        except ValueError:
            return

        if current_index < len(self.available_temperatures) - 1:
            self.temperature = self.available_temperatures[current_index + 1]
            self._ensure_valid_selection(reset_stack=True)
            self.refresh_view()

    def prev_temp(self):
        try:
            current_index = self.available_temperatures.index(self.temperature)
        except ValueError:
            return

        if current_index > 0:
            self.temperature = self.available_temperatures[current_index - 1]
            self._ensure_valid_selection(reset_stack=True)
            self.refresh_view()

    def toggle_channel(self):
        if len(self.channel_numbers) <= 1:
            self.logger.info("No channel variant available for current selection.")
            return

        current_index = self.channel_numbers.index(self.channel_number)
        self.channel_number = self.channel_numbers[(current_index + 1) % len(self.channel_numbers)]
        self._ensure_valid_selection(reset_stack=False)
        self.refresh_view()

    def _update_nav_buttons(self, current_channel_images):
        sample_ids = sorted({img.sample_id for img in self.images})
        has_prev_sample = any(sample_id < self.sample_id for sample_id in sample_ids)
        has_next_sample = any(sample_id > self.sample_id for sample_id in sample_ids)
        self.view.prev_sample_button.configure(state="normal" if has_prev_sample else "disabled")
        self.view.next_sample_button.configure(state="normal" if has_next_sample else "disabled")

        has_prev_site = any(
            img for img in self.images
            if img.sample_id == self.sample_id and img.site_number == self.site_number - 1
        )
        has_next_site = any(
            img for img in self.images
            if img.sample_id == self.sample_id and img.site_number == self.site_number + 1
        )
        self.view.prev_site_button.configure(state="normal" if has_prev_site else "disabled")
        self.view.next_site_button.configure(state="normal" if has_next_site else "disabled")

        has_prev_stack = self.stack_index > 0
        has_next_stack = self.stack_index < len(current_channel_images) - 1
        self.view.prev_stack_button.configure(state="normal" if has_prev_stack else "disabled")
        self.view.next_stack_button.configure(state="normal" if has_next_stack else "disabled")

        try:
            current_temp_index = self.available_temperatures.index(self.temperature)
        except ValueError:
            current_temp_index = -1
        has_prev_temp = current_temp_index > 0
        has_next_temp = 0 <= current_temp_index < len(self.available_temperatures) - 1
        self.view.prev_temp_button.configure(state="normal" if has_prev_temp else "disabled")
        self.view.next_temp_button.configure(state="normal" if has_next_temp else "disabled")
