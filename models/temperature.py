from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, column_property
from models import Base

class TemperatureProfile(Base):

    #following variables are sqlalchemy objects related to the Plate table in the database

    __tablename__ = "TemperatureProfile"
    id = Column(Integer, primary_key=True)
    description = Column(String)
    notes = Column(String)
    is_master = Column(Boolean)
    detail_line = relationship(
        "TemperatureProfileLine",
        backref="parent",
        cascade="all, delete-orphan",
        single_parent=True,)

class TemperatureProfileLine(Base):
    __tablename__ = "TemperatureProfileLine"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("TemperatureProfile.id"))
    temp_start  = Column(Float)
    temp_end  = Column(Float)
    duration_mins = Column(Integer)





