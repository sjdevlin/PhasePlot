from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship, column_property
from models import Base, Experiment



class ImageSet(Base): 

    __tablename__ = "ImageSet"
    id = Column(Integer, primary_key=True)
    annealer_id = Column(Integer, ForeignKey("Annealer.id"))
    temperature_profile_id = Column(Integer, ForeignKey("TemperatureProfile.id"))
    description = Column(String)
    notes = Column(String)
    lens = Column(String)
    scale_factor = Column(Float)
    number_of_sites = Column(Integer)
    stack_size = Column(Integer)
    stack_step_size = Column(Integer)
    led_number = Column(Integer)
    led_intensity = Column(Float)
    led_bitmask = Column(String)






