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
    channel_1_number = Column(Integer)
    channel_1_intensity = Column(Float)
    channel_1_bitmask = Column(String)
    channel_2_number = Column(Integer)
    channel_2_intensity = Column(Float)
    channel_2_bitmask = Column(String)
    autofocus = Column(Boolean, default=False)




