
from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, column_property
from models import Base


class Plate(Base):

    #following variables are sqlalchemy objects related to the Plate table in the database

    __tablename__ = "Plate"
    id = Column(Integer, primary_key=True)
    description = Column(String)
    outline_width = Column(Float)
    outline_length = Column(Float)
    outline_height = Column(Float)
    num_rows = Column(Integer)
    num_cols = Column(Integer)
    num_wells = column_property(num_rows * num_cols)
    centre_first_well_offset_x = Column(Float)
    centre_first_well_offset_y = Column(Float)
    well_dimension = Column(Float)
    well_depth = Column(Float)
    well_spacing_x = Column(Float)
    well_spacing_y = Column(Float)
    min_well_volume = Column(Float)
    max_well_volume = Column(Float)
    experiment = relationship(
        "Experiment",
        backref="plate",
        cascade="all, delete-orphan",
        single_parent=True,)









