
class MainPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.view.experiment_button.configure(command=self.open_experiment_window)
        self.view.results_button.configure(command=self.open_results_window)
        self.view.imaging_button.configure(command=self.open_imaging_window)
        self.view.plate_config_button.configure(command=self.open_plate_config_window)
        self.view.annealer_config_button.configure(command=self.open_annealer_config_window)
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
        from views import ResultRunListView
        from presenters import ResultRunListPresenter
        result_list_view = ResultRunListView()  # Create a new view
        experiment_presenter = ResultRunListPresenter(result_list_view, self.db)  # Initialize

    def open_imaging_window(self):
        pass

    def open_annealer_config_window(self):
        from views import AnnealerConfigView
        from presenters import AnnealerConfigPresenter
        annealer_config_view = AnnealerConfigView()  # Create a new view
        annealer_config_presenter = AnnealerConfigPresenter(annealer_config_view, self.db)  # Initialize the new presenter with the root widget

    def open_plate_config_window(self):
        from views import PlateConfigView
        from presenters import PlateConfigPresenter
        plate_config_view = PlateConfigView()  # Create a new view
        plate_config_presenter = PlateConfigPresenter(plate_config_view, self.db)  # Initialize the new presenter with the root widge


    def open_plate_sandbox_window(self):
        from views import AnnealerSandboxView
        from presenters import AnnealerSandboxPresenter
        plate_sandbox_view = AnnealerSandboxView()
        sandbox_presenter = AnnealerSandboxPresenter(plate_sandbox_view, self.db)
    
    def open_image_sandbox_window(self):
        from views import ImageSandboxView
        from presenters import ImageSandboxPresenter
        sandbox_view = ImageSandboxView()
        sandbox_presenter = ImageSandboxPresenter(sandbox_view, self.db)
    

