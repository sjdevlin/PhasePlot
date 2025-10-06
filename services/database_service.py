from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, joinedload
from models import *
from services import Logger, AppConfig

class DatabaseService:
    def __init__(self, db_url):
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

##Temperature Profile


    def get_all_plates(self):
        with self.Session() as session: 
           return session.query(Plate).options(joinedload(Plate.well)).all()

    def get_plate_by_id(self, plate_id):
        with self.Session() as session: 
           return session.query(Plate).filter_by(id=plate_id).first()

##Experiments

    def add_experiment(self, experiment):
        with self.Session() as session:
            session.add(experiment)
            session.commit()
            return experiment.id
        
    def get_experiment_by_id(self, exp_id):
        with self.Session() as session: 
           return session.query(Experiment).options(joinedload(Experiment.sample)).filter_by(id=exp_id).first()

    def get_all_experiments(self):
        with self.Session() as session:
            return session.query(Experiment).options(joinedload(Experiment.sample)).all()
          
    def update_experiment(self, experiment):
        with self.Session() as session:
            session.merge(experiment)  # Merges the detached object into the session
            session.commit()
            return True
                    
    def delete_experiment(self, experiment_id):
        with self.Session() as session:
            experiment = session.query(Experiment).filter_by(id=experiment_id).first()
            session.delete(experiment)
            session.commit()


## Samples
    def add_sample(self, sample):
        with self.Session() as session:
            session.add(sample)
            session.commit()
            return sample.id
        
    def update_sample(self, sample):
        with self.Session() as session:
            session.merge(sample)  # Merges the detached object into the session
            session.commit()
            return True

    def delete_sample(self, sample_id):
        with self.Session() as session:
            sample = session.query(Sample).filter_by(id=sample_id).first()
            session.delete(sample)
            session.commit()

    def get_sample_by_id(self, sample_id):
        with self.Session() as session: 
            return session.query(Sample).filter_by(id=sample_id).first()

    def get_samples_by_experiment_id(self, experiment_id):
        with self.Session() as session: 
            return session.query(Sample).options.filter_by(experiment_id=experiment_id).all()

#images

    def get_number_image_runs_by_exp_and_set(self, experiment_id, image_set_id):
        with self.Session() as session:
            return session.query(ImageRun).filter_by(experiment_id=experiment_id, image_set_id=image_set_id).count()

    def get_image_set_by_id(self, exp_id):
        with self.Session() as session: 
            return session.query(ImageSet).filter_by(id=exp_id).first()

    def get_all_image_sets(self):
        with self.Session() as session:
            return session.query(ImageSet).all()

    def add_image_run(self, image_run):
        with self.Session() as session:
            session.add(image_run)
            session.commit()
            return image_run.id

    def get_image_run_by_id(self, exp_id):
        with self.Session() as session: 
            return session.query(ImageRun).filter_by(id=exp_id).first()

    def get_all_image_runs(self):
        with self.Session() as session: 
            return session.query(ImageRun).options(joinedload(ImageRun.image)).all()

    def get_images_by_image_run_id(self, image_run_id):
        with self.Session() as session: 
            return session.query(Image).filter_by(image_run_id=image_run_id).order_by(Image.id).all()

    def add_image(self, image):
        with self.Session() as session:
            session.add(image)
            session.commit()
            return image.id
        
    def update_image_run(self, image_run):
        with self.Session() as session:
            session.merge(image_run)  # Merges the detached object into the session
            session.commit()
            return True

    def update_image(self, image):
        with self.Session() as session:
            session.merge(image)  # Merges the detached object into the session
            session.commit()
            return True

    def delete_image_run(self, image_run_id):
        with self.Session() as session:
            image_run = session.query(ImageRun).filter_by(id=image_run_id).first()
            session.delete(image_run)
            session.commit()


"""
    def update_experiment(self, experiment_id, new_status):
        with self.Session() as session:  # ✅ Automatically closes session
            experiment = session.query(Experiment).filter_by(id=experiment_id).first()
            if experiment:
                experiment.anneal_status = new_status
                session.commit() """