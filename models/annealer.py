
from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey, func
from sqlalchemy.orm import relationship, column_property
from models import Base


class Annealer(Base):
    __tablename__ = "Annealer"
    id = Column(Integer, primary_key=True)
    serial_number = Column(Integer, unique=True)
    plate_id = Column(Integer, ForeignKey("Plate.id"))
    description = Column(String)
    configured = Column(Boolean)
    num_wells = Column(Integer)
    number_active_sensors = Column(Integer)

    wells = relationship(
        "AnnealerWell",
        backref="annealer",
        cascade="all, delete-orphan",
        single_parent=True,
    )

    result_runs = relationship(
        "ResultRun",
        backref="annealer",
        # omit cascade/delete-orphan unless ResultSet is owned exclusively by Annealer
    )

class AnnealerWell(Base):
    __tablename__ = "AnnealerWell"
    id = Column(Integer, primary_key=True)
    annealer_id = Column(Integer, ForeignKey("Annealer.id"))
    well_index = Column(Integer)
    calibration_factor = Column(Float)
    sensor_address = Column(String)
    active = Column(Boolean)
    well_row = Column(String)
    well_column = Column(Integer)








