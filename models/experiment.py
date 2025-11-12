from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship, column_property
from models import Base, Plate
from datetime import datetime


class Experiment(Base): 

    #following variables are sqlalchemy objects related to the Experiment table in the database

    __tablename__ = "Experiment" #TODO: add an experiment detail table to store more information about the experiment
    id = Column(Integer, primary_key=True)
    plate_id = Column(Integer, ForeignKey("Plate.id"))
    # Enforced FK: each Experiment must reference a LiquidProtocol.
    # Deleting a referenced LiquidProtocol will be restricted by the DB (no cascade).
    liquid_protocol_id = Column(Integer, ForeignKey("LiquidProtocol.id"), nullable=False)
    liquid_protocol = relationship("LiquidProtocol", back_populates="experiments")
    description = Column(String)
    notes = Column(String)
    creation_date_time = Column(DateTime)
    dispensing_start_date_time = Column(DateTime)
    dispensing_finish_date_time = Column(DateTime)
    repeats = Column(Integer)
    oil = Column(String)  # Initially String for quick implementation; consider table later
    buffer = Column(String)  # Initially String for quick implementation; consider table later
    nanostar = Column(String)  # Initially here for quick implementation; consider table later
    max_ns_concentration = Column(Float)  # in microMolar. Initially here for quick implementation; consider table later
    status = Column(String)  # e.g., "in_progress", "completed", "failed"
    sample = relationship(
        "Sample",
        backref="parent",
        cascade="all, delete-orphan",
        single_parent=True,)

class LiquidProtocol(Base):

    #following variables are sqlalchemy objects related to the Experiment table in the database
    #always follows a dyadic aliquot scheme with 8 steps

    __tablename__ = "LiquidProtocol" #TODO: add an experiment detail table to store more information about the experiment
    id = Column(Integer, primary_key=True)
    description = Column(String)
    notes = Column(String)
    holding_temperature = Column(Float)  # in Celsius. Initially here for quick implementation; consider table later
    buffer_location = Column(String)  # e.g., "A1" (well descriptor)
    ns_dense_location = Column(String)  # e.g., "A2" (well descriptor)
    oil_location = Column(String)  # e.g., "D1" (well descriptor)
    emulsion_locations = Column(String)  # e.g., "B1" (well descriptor)
    creation_date_time = Column(DateTime)
    mix_aspirate_speed = Column(Float)  # Speed in µL/s
    mix_dispense_speed = Column(Float)  # Speed in µL/s
    number_mix_cycles = Column(Integer)
    mix_volume = Column(Float)  # Volume in µL
    mix_height_from_bottom = Column(Float)  # Height in mm
    mix_pipette = Column(String)  # e.g., "p20", "p300"
    dispense_pipette = Column(String)  # e.g., "p20", "p300"
    source_buffer_volume = Column(Float)  # Volume in µL
    source_NS_dense_volume = Column(Float)  # Volume in µL
    source_oil_volume = Column(Float)  # Volume in µL
    final_sample_dispense_volume = Column(Float)  # Volume in µL
    # Back-reference to experiments using this protocol
    experiments = relationship("Experiment", back_populates="liquid_protocol")

class Sample(Base):
    __tablename__ = "Sample"
    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey("Experiment.id"))
    well_row = Column(Integer)
    well_col = Column(Integer)
    well_descriptor = column_property(
        func.char(func.ascii('A') + well_row - 1) + func.cast(well_col, String)
    )
    ns_concentration = Column(Float)  # in microMolar
    image = relationship("Image", backref="sample", cascade="all, delete-orphan", single_parent=True)





