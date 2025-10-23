from sqlalchemy import Column, String, Integer, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, relationship
from models import Base

class ResultSet(Base): 

    __tablename__ = "ResultSet"
    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey("Experiment.id"))
    image_set_id = Column(Integer, ForeignKey("ImageSet.id"))
    annealer_id = Column(Integer, ForeignKey("Annealer.id"))
    annealing_profile_id = Column(Integer, ForeignKey("AnnealingProfile.id"))
    description = Column(String)
    notes = Column(String)
    start_date_time = Column(DateTime)
    finish_date_time = Column(DateTime)
    number_of_samples = Column(Integer)
    status = Column(String)
    image = relationship(
        "Image",
        backref="parent",
        cascade="all, delete-orphan",
        single_parent=True,)

class RunData(Base):
    __tablename__ = "RunData"
    id = Column(Integer, primary_key=True)
    sample_id = Column(Integer, ForeignKey("Sample.id"))
    result_set_id = Column(Integer, ForeignKey("ResultSet.id"))
    reading_date_time = Column(DateTime)
    elapsed_minutes = Column(Integer)
    target_temperature = Column(Float)
    actual_temperature = Column(Float)
    heat_applied = Column(Integer)
