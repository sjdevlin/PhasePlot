
from sqlalchemy import Column, String, Integer, Float, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from models import Base


class Component(Base):

    #following variables are sqlalchemy objects related to the Plate table in the database

    __tablename__ = "Component"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String)

class Solution(Base):

    #following variables are sqlalchemy objects related to the Plate table in the database

    __tablename__ = "Solution"
    id = Column(Integer, primary_key=True)
    sample_id = Column(Integer, ForeignKey("Sample.id"))
    component_id = Column(Integer, ForeignKey("Component.id"))
    volume = Column(Float)
    component = relationship("Component", backref="solutions", cascade="all, delete-orphan", single_parent=True)    


