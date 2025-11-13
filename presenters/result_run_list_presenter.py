from models import Experiment, Sample
from services import AppConfig, ImageProcessor

class ResultRunListPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.view.res_bind_row_selection(self.on_res_row_selected)
        self.refresh_view()
        self.view.review_button.configure(command=self.review_result_run)
        self.view.process_button.configure(command=self.process_result_run)
        self.selected_res_row = None


    def on_res_row_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_res_row = self.view.get_id_of_selected_res_row()
        if self.selected_res_row:
            self.view.enable_process_button()
            self.view.enable_review_button()

    def refresh_view(self):
#        self.selected_row = None
        results = self.db.get_all_result_runs() #TODO think about whether different illumination types should be separated 

        # Convert SQLAlchemy objects into dictionaries or tuples
        data = [
            (
            res.id,
            res.description,
            res.number_of_samples,
            len(res.image),
            res.start_date_time.strftime('%Y-%m-%d %H:%M:%S') if res.start_date_time else ""
            )
            for res in results
        ]
        self.view.list_results(data)

        self.view.disable_review_button()
        self.view.disable_process_button()

    def process_result_run(self):
        from views import LogView
        from services import Logger

        log_file_path = Logger().log_file
        #TODO consider log window to always access singleton logger and no need to pass the reference
        
        # Create a new window to display the log file in real time.
        log_window = LogView(self.view.root_window, log_file_path)

        self.image_processor = ImageProcessor(db_service=self.db, match_tolerance = 10)  
        self.image_processor.analyze(self.selected_res_row)

        pass
        
    def review_result_run(self):

        from views import ResultRunDetailView
        from services import Logger
        from presenters import ResultRunDetailPresenter

        results_id = self.view.get_id_of_selected_res_row()
        results_detail_view = ResultRunDetailView()  # Create a new view
        results_detail_presenter = ResultRunDetailPresenter(view=results_detail_view, db=self.db, result_run_id=results_id)  # Initialize the new presenter with the root widget

