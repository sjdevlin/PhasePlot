from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship, column_property
from models import Base, Experiment



class ImageSet(Base): 

    __tablename__ = "ImageSet"
    id = Column(Integer, primary_key=True)
    description = Column(String)
    notes = Column(String)
    lens = Column(String)
    scale_factor = Column(Float)
    number_of_sites = Column(Integer)
    stack_size = Column(Integer)
    stack_step_size = Column(Integer)
    led_number = Column(Integer) #TODO: this all needs re writing - currently in the config.yaml and result_run_operator.py but should be in the database and read from there
    led_intensity = Column(Float)
    led_bitmask = Column(String)






