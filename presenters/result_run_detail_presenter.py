from models import Experiment, Sample
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
        self.view.toggle_led_button.configure(command=self.toggle_led)

        self.images = self.db.get_images_by_result_run_id(result_run_id)

        if not self.images:
            self.logger.error(f"No images found for result run {result_run_id}.")
            return

        # Sort images by sample number, site number, then stack index and pick the first image as a reference
        first_reference = sorted(self.images, key=lambda img: (img.sample_id, img.site_number))[0]
        self.sample_id = first_reference.sample_id
        self.site_number = first_reference.site_number
        self.led_offset = first_reference.stack_number % 2
        self._update_available_temperatures()
        self.temperature = self.available_temperatures[0]
        self.stack_number = self._get_index_of_sharpest_image()
        # Filter images from the first stack that have the same sample and site number as the reference
        self.refresh_view()

    def _update_available_temperatures(self):
        """Update the list of available temperatures for the current sample and site."""
        self.available_temperatures = sorted(list({img.temperature for img in self.images 
                                              if img.sample_id == self.sample_id and img.site_number == self.site_number}), reverse=True)
        if not self.available_temperatures:
             self.available_temperatures = [0]


    def refresh_view(self):

        sample = self.db.get_sample_by_id(self.sample_id)
        if not sample:
            self.logger.error(f"No sample found with ID {self.sample_id}.")
            return
        
        self.view.update_led_button(self.led_offset)

        actual_stack = self.stack_number + self.led_offset

        meta_data = f"Sample: {self.sample_id} Row: {sample.well_row}, Column: {sample.well_column}"
        meta_data += f"\nSite: {self.site_number}, Stack: {self.stack_number}"
        meta_data += f"\nLED Offset: {self.led_offset}"

        candidates = [img for img in self.images
                      if img.sample_id == self.sample_id and
                         img.site_number == self.site_number and
                         img.stack_number == actual_stack and
                         img.temperature == self.temperature]

        self._update_nav_buttons()

        focus_score = next((img.focus_score for img in candidates), None)

        if focus_score is None:
            self.logger.warning(f"No focus score found for sample {self.sample_id}, site {self.site_number}, stack {self.stack_number}, temp {self.temperature}.")
            return

        meta_data += f"\nFocus Score: {focus_score:.2f}"
        meta_data += f"\nTemperature: {self.temperature}"
        # Approximate time at temperature using logic or existing fields
        # Ideally we'd have this in the Image model, but for now we can maybe omit or placeholders

        try:
            # Get the image file path - no need to prepend /Users/dev
            image_file_path = next((img.file_path for img in candidates), None)
            if image_file_path is None:
                raise StopIteration
            
            # Check if path is already absolute, if not make it relative to current directory
            image_file_path = f"{self.app_config.get('local_file_path', '')}{image_file_path}"

            self.view.show_image(image_file_path, meta_data)
        except StopIteration:
            self.logger.warning(f"No image found for sample {self.sample_id}, site {self.site_number}, stack {self.stack_number}, temp {self.temperature}.")
        except Exception as e:
            self.logger.error(f"Unexpected error while refreshing image view: {e}")

    def _get_index_of_sharpest_image(self):

        stack = [img for img in self.images
                      if img.sample_id == self.sample_id and
                          img.site_number == self.site_number and
                          img.temperature == self.temperature and
                          (img.stack_number % 2) == self.led_offset]

        # Select the first stack index matching the LED offset
        if not stack:
            self.logger.warning(f"No stack found for sample {self.sample_id}, site {self.site_number}.")
            return 0

        first_image = min(stack, key=lambda img: img.stack_number)
        first_stack_number = first_image.stack_number
        return first_stack_number - self.led_offset

    def next_sample(self):
        #Navigate to the sharpest image in the first site of the next sample
        sorted_images = sorted({img.sample_id for img in self.images})

        try:
            next_sample_id = next(s for s in sorted_images if s > self.sample_id)
            self.sample_id = next_sample_id
            self.site_number = 0
            self._update_available_temperatures()
            self.temperature = self.available_temperatures[0]
            self.stack_number = self._get_index_of_sharpest_image()
            self.refresh_view()
        except StopIteration:
            self.logger.info("No next sample available.")


    def prev_sample(self):
        sorted_images = sorted({img.sample_id for img in self.images})

        try:
            prev_candidates = [s for s in sorted_images if s < self.sample_id]
            prev_sample = prev_candidates[-1]
            self.sample_id = prev_sample
            self.site_number = 0
            self._update_available_temperatures()
            self.temperature = self.available_temperatures[0]
            self.stack_number = self._get_index_of_sharpest_image()
            self.refresh_view()
        except IndexError:
            self.logger.info("No previous sample available.")


    def next_site(self):

        next_site = self.site_number + 1
        if any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == next_site):
            self.site_number = next_site
        self.stack_number = self._get_index_of_sharpest_image()
        self.refresh_view()

    def prev_site(self):
        prev_site = self.site_number - 1
        if any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == prev_site):
            self.site_number = prev_site
        self.stack_number = self._get_index_of_sharpest_image()
        self.refresh_view()

    def next_stack(self):
        next_stack = self.stack_number + 2
        actual_next = next_stack + self.led_offset
        if any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == self.site_number and img.stack_number == actual_next  and img.temperature == self.temperature):
            self.stack_number = next_stack
        self.refresh_view()

    def prev_stack(self):
        prev_stack = self.stack_number - 2
        actual_prev = prev_stack + self.led_offset
        if any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == self.site_number and img.stack_number == actual_prev and img.temperature == self.temperature):
            self.stack_number = prev_stack
        self.refresh_view()

    def next_temp(self):
        try:
            current_index = self.available_temperatures.index(self.temperature)
            if current_index < len(self.available_temperatures) - 1:
                self.temperature = self.available_temperatures[current_index + 1]
                self.stack_number = self._get_index_of_sharpest_image()
                self.refresh_view()
        except ValueError:
            pass

    def _update_nav_buttons(self):
        # Sample navigation
        sample_ids = sorted({img.sample_id for img in self.images})
        has_prev_sample = any(s < self.sample_id for s in sample_ids)
        has_next_sample = any(s > self.sample_id for s in sample_ids)
        self.view.prev_sample_button.configure(state="normal" if has_prev_sample else "disabled")
        self.view.next_sample_button.configure(state="normal" if has_next_sample else "disabled")

        # Site navigation
        has_prev_site = any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == self.site_number - 1)
        has_next_site = any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == self.site_number + 1)
        self.view.prev_site_button.configure(state="normal" if has_prev_site else "disabled")
        self.view.next_site_button.configure(state="normal" if has_next_site else "disabled")

        # Stack navigation (offset-aware)
        next_stack = self.stack_number + 2
        prev_stack = self.stack_number - 2
        actual_next = next_stack + self.led_offset
        actual_prev = prev_stack + self.led_offset
        has_next_stack = any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == self.site_number and img.stack_number == actual_next and img.temperature == self.temperature)
        has_prev_stack = any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == self.site_number and img.stack_number == actual_prev and img.temperature == self.temperature)
        self.view.next_stack_button.configure(state="normal" if has_next_stack else "disabled")
        self.view.prev_stack_button.configure(state="normal" if has_prev_stack else "disabled")

        # Temperature navigation
        try:
            current_index = self.available_temperatures.index(self.temperature)
        except ValueError:
            current_index = -1
        has_prev_temp = current_index > 0
        has_next_temp = 0 <= current_index < len(self.available_temperatures) - 1
        self.view.prev_temp_button.configure(state="normal" if has_prev_temp else "disabled")
        self.view.next_temp_button.configure(state="normal" if has_next_temp else "disabled")

    def prev_temp(self):
        try:
            current_index = self.available_temperatures.index(self.temperature)
            if current_index > 0:
                self.temperature = self.available_temperatures[current_index - 1]
                self.stack_number = self._get_index_of_sharpest_image()
                self.refresh_view()
        except ValueError:
            pass

    def toggle_led(self):
        next_offset = 1 - self.led_offset
        actual_stack = self.stack_number + next_offset
        if not any(img for img in self.images if img.sample_id == self.sample_id and img.site_number == self.site_number and img.stack_number == actual_stack and img.temperature == self.temperature):
            self.logger.info("No LED variant available for current selection.")
            return
        self.led_offset = next_offset
        self.refresh_view()
