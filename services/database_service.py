from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, joinedload
from models import *
from models.results import ResultRun
from services import Logger, AppConfig

class DatabaseService:
    def __init__(self, db_url):
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

##Temperature Profile

    def get_temperature_profile_by_id(self, temp_profile_id):
        with self.Session() as session: 
           return session.query(TemperatureProfile).filter_by(id=temp_profile_id).first()

##Annealer

    def get_annealer_by_serial_number(self, ser_number):
        with self.Session() as session: 
           return session.query(Annealer).options(joinedload(Annealer.well)).filter_by(serial_number=ser_number).first()


##Plates

    def get_all_plates(self):
        with self.Session() as session: 
           return session.query(Plate).options(joinedload(Plate.well)).all()

    def get_plate_by_id(self, plate_id):
        with self.Session() as session: 
           return session.query(Plate).options(joinedload(Plate.well)).filter_by(id=plate_id).first()
        
    def get_plate_by_serial_number(self, ser_number):
        with self.Session() as session: 
           return session.query(Plate).options(joinedload(Plate.well)).filter_by(serial_number=ser_number).first()

    def add_plate(self, plate):
        with self.Session() as session:
            session.add(plate)
            session.commit()
            return plate.id
        
    def update_plate(self, plate):
        with self.Session() as session:
            session.merge(plate)  # Merges the detached object into the session
            session.commit()
            return True

#Annealer
    def get_annealer_by_id(self, annealer_id):
        with self.Session() as session: 
           return session.query(Annealer).options(joinedload(Annealer.well)).filter_by(id=annealer_id).first()

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
          
    def update_experiment(self, experiment):#TODO check this is ever used now - may be a hnag over from systemXnative
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


#Results

    def get_all_result_sets(self):
        with self.Session() as session:
            return session.query(ResultSet).all()
        
    def get_result_set_by_id(self, result_set_id):
        with self.Session() as session: 
            return session.query(ResultSet).filter_by(id=result_set_id).first()
        
    def get_all_result_runs(self):
        with self.Session() as session: 
            return session.query(ResultRun).options(joinedload(ResultRun.image)).all()

    def get_number_result_runs_by_exp_and_set(self, experiment_id, result_set_id):
        with self.Session() as session:
            return session.query(ResultRun).filter_by(experiment_id=experiment_id, result_set_id=result_set_id).count()

    def add_result_run(self, result_run):
        with self.Session() as session:
            session.add(result_run)
            session.commit()
            return result_run.id

    def add_result_run_data(self, result_run_data):
        with self.Session() as session:
            session.add(result_run_data)
            session.commit()
            return result_run_data.id
        
    def add_image(self, image):
        with self.Session() as session:
            session.add(image)
            session.commit()
            return image.id
        
    def update_image(self, image):
        with self.Session() as session:
            session.merge(image)  # Merges the detached object into the session
            session.commit()
            return True



    def get_result_run_by_id(self, result_run_id):
        with self.Session() as session: 
            return session.query(ResultRun).filter_by(id=result_run_id).first()


    def get_images_by_result_run_id(self, result_run_id):
        with self.Session() as session: 
            return session.query(Image).filter_by(result_run_id=result_run_id).order_by(Image.id).all()

    def update_result_run(self, result_run):
        with self.Session() as session:
            session.merge(result_run)  # Merges the detached object into the session
            session.commit()
            return True

    def delete_result_run(self, result_run_id):
        with self.Session() as session:
            result_run = session.query(ResultRun).filter_by(id=result_run_id).first()
            session.delete(result_run)
            session.commit()


#images

    def get_image_set_by_id(self, image_set_id):
        with self.Session() as session: 
            return session.query(ImageSet).filter_by(id=image_set_id).first()

    def get_all_image_sets(self):
        with self.Session() as session:
            return session.query(ImageSet).all()
        
#Liquid Protocols

    def get_liquid_protocol_by_id(self, protocol_id):
        with self.Session() as session:
            return session.query(LiquidProtocol).filter_by(id=protocol_id).first()

"""
    def update_experiment(self, experiment_id, new_status):
        with self.Session() as session:  # ✅ Automatically closes session
            experiment = session.query(Experiment).filter_by(id=experiment_id).first()
            if experiment:
                experiment.anneal_status = new_status
                session.commit() """