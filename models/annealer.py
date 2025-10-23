
from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, column_property
from models import Base


class Annealer(Base):
    __tablename__ = "Annealer"
    id = Column(Integer, primary_key=True)
    description = Column(String)
    configured = Column(Boolean)
    well = relationship(
        "AnnealerWell",
        backref="Annealer",
        cascade="all, delete-orphan",
        single_parent=True,)
    experiment = relationship(
        "Experiment",
        backref="Annealer",
        cascade="all, delete-orphan",
        single_parent=True,)
    number_active_sensors = Column(Integer)

class AnnealerWell(Base):
    __tablename__ = "AnnealerWell"
    id = Column(Integer, primary_key=True)
    annealer_id = Column(Integer, ForeignKey("Annealer.id"))
    well_index = Column(Integer)
    calibration_factor = Column(Float)
    sensor_address = Column(String)
    active = Column(Boolean)
    well_row = Column(Integer)
    well_col = Column(Integer)
    well_descriptor = Column(String)








