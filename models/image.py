from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, relationship, column_property
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
    led_number = Column(Integer)
    led_intensity = Column(Float)
    led_bitmask = Column(String)

    image = relationship(
        "ImageRun",
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






