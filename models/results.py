from sqlalchemy import Column, String, Integer, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from models import Base

class ResultSet(Base): 

    __tablename__ = "ResultSet"
    id = Column(Integer, primary_key=True)
    image_set_id = Column(Integer, ForeignKey("ImageSet.id"))
    annealer_id = Column(Integer, ForeignKey("Annealer.id"))
    temperature_profile_id = Column(Integer, ForeignKey("TemperatureProfile.id"))
    description = Column(String)
    notes = Column(String)

class ResultRun(Base): 

    __tablename__ = "ResultRun"
    id = Column(Integer, primary_key=True)
    result_set_id = Column(Integer, ForeignKey("ResultSet.id"))
    experiment_id = Column(Integer, ForeignKey("Experiment.id"))
    description = Column(String)
    notes = Column(String)
    start_date_time = Column(DateTime)
    finish_date_time = Column(DateTime)
    status = Column(String)
    number_of_samples = Column(Integer)
    pid_kp = Column(Float)
    pid_ki = Column(Float)
    pid_kd = Column(Float)
    image = relationship(
        "Image",
        backref="parent",
        cascade="all, delete-orphan",
        single_parent=True,)
    result_run_data = relationship(
        "ResultRunData",
        backref="parent",
        cascade="all, delete-orphan",
        single_parent=True,)


class Image(Base):
    __tablename__ = "Image"
    id = Column(Integer, primary_key=True)
    sample_id = Column(Integer, ForeignKey("Sample.id"))
    result_set_id = Column(Integer, ForeignKey("ResultSet.id"))
    site_number = Column(Integer)
    stack_number = Column(Integer)
    dimension_x = Column(Integer)
    dimension_y = Column(Integer)
    file_path = Column(String)
    timestamp = Column(DateTime)
    temperature = Column(Float)
    focus_score = Column(Float)
    average_droplet_size = Column(Float)
    standard_deviation_droplet_size = Column(Float)

class ResultRunData(Base):
    __tablename__ = "RunData"
    id = Column(Integer, primary_key=True)
    sample_id = Column(Integer, ForeignKey("Sample.id"))
    result_run_id = Column(Integer, ForeignKey("ResultRun.id"))
    reading_date_time = Column(DateTime)
    elapsed_minutes = Column(Integer)
    target_temperature = Column(Float)
    actual_temperature = Column(Float)
    heat_applied = Column(Integer)
