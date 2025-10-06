from models import Experiment, Sample
from services import AppConfig, ImageProcessor

class ImageRunListPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.view.res_bind_row_selection(self.on_res_row_selected)
        self.refresh_view()
        self.view.review_button.configure(command=self.review_image_run)
        self.view.process_button.configure(command=self.process_image_run)
        self.selected_res_row = None


    def on_res_row_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_res_row = self.view.get_id_of_selected_res_row()
        if self.selected_res_row:
            self.view.enable_process_button()
            self.view.enable_review_button()

    def refresh_view(self):
#        self.selected_row = None
        results = self.db.get_all_image_runs() #TODO think about whether different illumination types should be separated 

        # Convert SQLAlchemy objects into dictionaries or tuples
        data = [
            (
            res.id,
            res.description,
            res.number_of_samples,
            len(res.image),
            res.image_run_start_date_time.strftime('%Y-%m-%d %H:%M:%S') if res.image_run_start_date_time else ""
            )
            for res in results
        ]
        self.view.list_results(data)

        self.view.disable_review_button()
        self.view.disable_process_button()

    def process_image_run(self):
        from views import LogView
        from services import Logger

        log_file_path = Logger().log_file
        #TODO consider log window to always access singleton logger and no need to pass the reference
        
        # Create a new window to display the log file in real time.
        log_window = LogView(self.view.root_window, log_file_path)

        self.image_processor = ImageProcessor(db_service=self.db, match_tolerance = 10)  
        self.image_processor.analyze(self.selected_res_row)

        pass
        
    def review_image_run(self):

        from views import ImageRunDetailView
        from services import Logger
        from presenters import ImageRunDetailPresenter

        results_id = self.view.get_id_of_selected_res_row()
        results_detail_view = ImageRunDetailView()  # Create a new view
        results_detail_presenter = ImageRunDetailPresenter(view=results_detail_view, db=self.db, image_run_id=results_id)  # Initialize the new presenter with the root widget


