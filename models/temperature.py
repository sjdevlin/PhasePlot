from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, column_property
from models import Base

class TemperatureProfile(Base):

    #following variables are sqlalchemy objects related to the Plate table in the database

    __tablename__ = "TemperatureProfile"
    id = Column(Integer, primary_key=True)
    description = Column(String)
    notes = Column(String)
    start_temp  = Column(Float)
    end_temp  = Column(Float)
    step_interval_mins = Column(Float)
    soak_time_seconds = Column(Integer)





