
from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey, func
from sqlalchemy.orm import relationship, column_property
from models import Base


class Plate(Base):

    #following variables are sqlalchemy objects related to the Plate table in the database

    __tablename__ = "Plate"
    id = Column(Integer, primary_key=True)
    description = Column(String)
    opentrons_name = Column(String) #e.g. Custom 36 Well Plate 35 µL
    outline_width = Column(Float)
    outline_length = Column(Float)
    outline_height = Column(Float)
    num_rows = Column(Integer)
    num_cols = Column(Integer)
    num_wells = column_property(num_rows * num_cols)
    centre_first_well_offset_x = Column(Float)
    centre_first_well_offset_y = Column(Float)
    well_type = Column(String)  #e.g. Circular, Square
    well_dimension = Column(Float)
    well_depth = Column(Float)
    well_spacing_x = Column(Float)
    well_spacing_y = Column(Float)
    min_well_volume = Column(Float)
    max_well_volume = Column(Float)
    well = relationship(
        "PlateWell",
        backref="plate",
        cascade="all, delete-orphan",
        single_parent=True,)
    # Plate is independent of Experiment; do not cascade delete experiments
    experiment = relationship(
        "Experiment",
        backref="plate",
    )
    
def get_well_index(self, row, column):
                for candidate in getattr(self, "well", []) or []:
                    if getattr(candidate, "well_row", None) == row and getattr(candidate, "well_column", None) == column:
                        return candidate

class PlateWell(Base):
    __tablename__ = "PlateWell"
    id = Column(Integer, primary_key=True)
    plate_id = Column(Integer, ForeignKey("Plate.id"))
    well_row = Column(Integer)
    well_col = Column(Integer)
    well_descriptor = column_property(
        func.char(func.ascii('A') + well_row - 1) + func.cast(well_col, String)
    )
    z_height = Column(Float)








