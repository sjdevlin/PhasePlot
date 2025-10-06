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
    stack_step_size = Column(Float)
    led_number = Column(Integer)
    led_intensity = Column(Float)
    led_bitmask = Column(String)

    image = relationship(
        "ImageRun",
        backref="parent",
        cascade="all, delete-orphan",
        single_parent=True,)


class ImageRun(Base): 

    __tablename__ = "ImageRun"
    id = Column(Integer, primary_key=True)
    image_set_id = Column(Integer, ForeignKey("ImageSet.id"))
    experiment_id = Column(Integer, ForeignKey("Experiment.id"))
    description = Column(String)
    notes = Column(String)
    image_run_start_date_time = Column(DateTime)
    image_run_finish_date_time = Column(DateTime)
    image_run_status = Column(String)
    number_of_samples = Column(Integer)
    image = relationship(
        "Image",
        backref="parent",
        cascade="all, delete-orphan",
        single_parent=True,)

class Image(Base):
    __tablename__ = "Image"
    id = Column(Integer, primary_key=True)
    sample_id = Column(Integer, ForeignKey("Sample.id"))
    image_run_id = Column(Integer, ForeignKey("ImageRun.id"))
    image_site_number = Column(Integer)
    image_stack_number = Column(Integer)
    image_dimension_x = Column(Integer)
    image_dimension_y = Column(Integer)
    image_file_path = Column(String)
    image_timestamp = Column(DateTime)
    image_focus_score = Column(Float)
    average_droplet_size = Column(Float)
    standard_deviation_droplet_size = Column(Float)






