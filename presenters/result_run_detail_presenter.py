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

        self.images = self.db.get_images_by_result_run_id(result_run_id)

        if not self.images:
            self.logger.error(f"No images found for result run {result_run_id}.")
            return

        # Sort images by sample number, site number, then stack index and pick the first image as a reference
        first_reference = sorted(self.images, key=lambda img: (img.sample_id, img.image_site_number))[0]
        self.sample_id = first_reference.sample_id
        self.site_number = first_reference.image_site_number
        self.stack_number = self._get_index_of_sharpest_image()
        # Filter images from the first stack that have the same sample and site number as the reference
        self.refresh_view()

    def refresh_view(self):

        sample = self.db.get_sample_by_id(self.sample_id)
        if not sample:
            self.logger.error(f"No sample found with ID {self.sample_id}.")
            return
        
        meta_data = f"Sample: {self.sample_id} Row: {sample.well_row}, Column: {sample.well_column}"
        meta_data += f"\nSite: {self.site_number}, Stack: {self.stack_number}"

        focus_score = next(
                (img.image_focus_score for img in self.images
                if img.sample_id == self.sample_id and
                   img.image_site_number == self.site_number and
                   img.image_stack_number == self.stack_number),
                None
            )

        if focus_score is None:
            self.logger.warning(f"No focus score found for sample {self.sample_id}, site {self.site_number}, stack {self.stack_number}.")
            return

        meta_data += f"\nFocus Score: {focus_score:.2f}"

        try:
            # Get the image file path - no need to prepend /Users/dev
            image_file_path = next(
                (img.image_file_path for img in self.images
                if img.sample_id == self.sample_id and
                   img.image_site_number == self.site_number and
                   img.image_stack_number == self.stack_number),
                None
            )
            if image_file_path is None:
                raise StopIteration
            
            # Check if path is already absolute, if not make it relative to current directory
            image_file_path = f"{self.app_config.get('local_file_path')}{image_file_path}"

            self.view.show_image(image_file_path, meta_data)
        except StopIteration:
            self.logger.warning(f"No image found for sample {self.sample_id}, site {self.site_number}, stack {self.stack_number}.")
        except Exception as e:
            self.logger.error(f"Unexpected error while refreshing image view: {e}")

    def _get_index_of_sharpest_image(self):

        stack = [img for img in self.images
            if img.sample_id == self.sample_id and
               img.image_site_number == self.site_number]

        # Select the image with the best image_focus_score from these images
        if not stack:
            self.logger.warning(f"No stack found for sample {self.sample_id}, site {self.site_number}.")
            return 0

        best_image = max(stack, key=lambda img: img.image_focus_score)
        best_stack_number = best_image.image_stack_number


        return best_stack_number

    def next_sample(self):
        #Navigate to the sharpest image in the first site of the next sample
        sorted_images = sorted({img.sample_id for img in self.images})

        try:
            next_sample_id = next(s for s in sorted_images if s > self.sample_id)
            self.sample_id = next_sample_id
            self.site_number = 0
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
            self.stack_number = self._get_index_of_sharpest_image()
            self.refresh_view()
        except IndexError:
            self.logger.info("No previous sample available.")


    def next_site(self):

        next_site = self.site_number + 1
        if any(img for img in self.images if img.sample_id == self.sample_id and img.image_site_number == next_site):
            self.site_number = next_site
        self.stack_number = self._get_index_of_sharpest_image()
        self.refresh_view()

    def prev_site(self):
        prev_site = self.site_number - 1
        if any(img for img in self.images if img.sample_id == self.sample_id and img.image_site_number == prev_site):
            self.site_number = prev_site
        self.stack_number = self._get_index_of_sharpest_image()
        self.refresh_view()

    def next_stack(self):
        next_stack = self.stack_number + 1
        if any(img for img in self.images if img.sample_id == self.sample_id and img.image_site_number == self.site_number and img.image_stack_number == next_stack):
            self.stack_number = next_stack
        self.refresh_view()

    def prev_stack(self):
        prev_stack = self.stack_number - 1
        if any(img for img in self.images if img.sample_id == self.sample_id and img.image_site_number == self.site_number and img.image_stack_number == prev_stack):
            self.stack_number = prev_stack
        self.refresh_view()
