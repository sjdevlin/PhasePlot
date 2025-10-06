
class MainPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.view.experiment_button.configure(command=self.open_experiment_window)
        self.view.annealing_button.configure(command=self.open_annealing_window)
        self.view.results_button.configure(command=self.open_results_window)
        self.view.imaging_button.configure(command=self.open_imaging_window)
        self.view.plate_config_button.configure(command=self.open_plate_config_window)
        self.view.plate_sandbox_button.configure(command=self.open_plate_sandbox_window)
        self.view.image_sandbox_button.configure(command=self.open_image_sandbox_window)

    def open_experiment_window(self):
        from views import ExperimentListView
        from presenters import ExperimentListPresenter
        experiment_list_view = ExperimentListView()  # Create a new view
        experiment_presenter = ExperimentListPresenter(experiment_list_view, self.db)  # Initialize the new presenter with the root widget

    def open_annealing_window(self):
        pass

    def open_results_window(self):
        from views import ImageRunListView
        from presenters import ImageRunListPresenter
        result_list_view = ImageRunListView()  # Create a new view
        experiment_presenter = ImageRunListPresenter(result_list_view, self.db)  # Initialize the new presenter with the root widget

    def open_imaging_window(self):
        pass

    def open_plate_config_window(self):
        pass

    def open_plate_sandbox_window(self):
        pass
    
    def open_image_sandbox_window(self):
        from views import ImageSandboxView
        from presenters import ImageSandboxPresenter
        sandbox_view = ImageSandboxView()
        sandbox_presenter = ImageSandboxPresenter(sandbox_view, self.db)
    

