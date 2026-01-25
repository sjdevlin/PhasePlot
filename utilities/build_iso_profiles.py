"""
Script to create temperature profiles and a new experiment with samples assigned profiles.

Each temperature profile:
    - Ramps up from 20 to a fixed temperature over 30 minutes.
    - Then ramps down back to 20 over 30 minutes.
The fixed temperature is set in 0.5 increments from 34 to 50.
Finally, an experiment is created on plate with plate_id=5. For every active well on the plate,
a sample is created and a temperature profile is assigned. Wells are sorted by their well_index
so that profiles with adjacent temperatures are assigned to adjacent wells.
"""

import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import classes from the attached modules (adjust imports as needed)
from models import Plate, Sample, Experiment
from services import DatabaseService, AppConfig
from datetime import datetime

def create_temperature_profiles(db):
    """
    Create 34 temperature profiles, each composed of two TemperatureProfileLine entries.
    
    Returns:
        List of TemperatureProfile objects.
    """
    # Create fixed temperatures from 34°C to 50.5°C (inclusive) in 0.5°C increments.
    fixed_temps = np.arange(38.5, 55 + 0.001, 0.5).tolist()  # Adding a small epsilon to include 50.5
    profiles = []
    
    for temp in fixed_temps:
        # Create a new temperature profile (assign a name or description if desired)
        new_profile = TemperatureProfile(description=f"60 Min ISO at {temp:.1f}", 
        notes = f"60 min ramp up from ambient.  90 min at {temp:.1f}.  60 min ramp down to ambient.")
        
        # Create the ramp-up line: from 20°C to the fixed temperature over 30 minutes.
        new_profile.detail_line = []

        new_profile.detail_line.append(TemperatureProfileLine(temp_end=temp, duration_mins=60))
        new_profile.detail_line.append(TemperatureProfileLine(temp_end=temp, duration_mins=90))
        new_profile.detail_line.append(TemperatureProfileLine(temp_end=25, duration_mins=60))
        
        # Save the temperature profile (which includes its lines) to the database.
        profile_id = db.add_temperature_profile(new_profile)
        profiles.append(profile_id)
    
    return profiles

def create_experiment_with_samples(db, profiles):
    """
    Create a new experiment on plate with plate_id=5, create samples for each active well,
    and assign one temperature profile per sample such that profiles with adjacent fixed temperatures
    are assigned to adjacent wells (by well_index).
    
    Args:
        profiles: List of TemperatureProfile objects.
    
    Returns:
        The created Experiment object.
    """
    # Retrieve the plate with plate_id=5.
    plate = db.get_plate_by_id(5)
    
    # Create a new experiment with an appropriate description and notes.
    experiment = Experiment(
        plate=plate,
        description="IsoThermal Test 38.5 - 55C",
        notes="34 sample iso thermal test with profiles to 55C in 0.5C increments, 60 min ramp up, 90 min hold, 60 min ramp down.",
        anneal_status = 'Not Run', 
        creation_date_time = datetime.now()
    )
     
    # Assign each profile to a sample corresponding to a well.
    experiment.sample = []
    profile_index = 0

    active_wells = [w for w in sorted(plate.well, key=lambda w: w.well_index) if w.active]
    for i, well in enumerate(active_wells):
        experiment.sample.append(
            Sample(well_index=well.well_index, temperature_profile_id=profiles[i], plate_well_id=well.id)
        )

    # Save the experiment (and its samples) to the database.
    experiment_id = db.add_experiment(experiment)
    
    return experiment_id

def main():
    # Create temperature profiles and save them.
    config = AppConfig("./config.yaml")
    db = DatabaseService(config.get("sqlite_db"))
    profiles = create_temperature_profiles(db)
    print(f"Created {len(profiles)} temperature profiles.")
    
    # Create the experiment and assign the profiles to samples.
    experiment = create_experiment_with_samples(db, profiles)
    print(f"Experiment {experiment} created successfully and samples assigned to active wells on plate 5.")

if __name__ == "__main__":
    main()