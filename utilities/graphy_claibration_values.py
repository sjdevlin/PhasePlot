import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

# Load data
# Get the path of the current script directory
script_dir = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(script_dir, 'calibrate.csv')
data = pd.read_csv(file_path)
data.columns = ['Set', 'Sensor', 'Calibration']

# Calculate standard deviation for each sensor
std_by_sensor = data.groupby('Sensor')['Calibration'].std().reset_index(name='StdDev')

# Plotting
fig, ax = plt.subplots(figsize=(14, 7))

# Plot calibration values
colors = ['red', 'green', 'orange']

for idx, set_num in enumerate(sorted(data['Set'].unique())):
    subset = data[data['Set'] == set_num]
    ax.scatter(subset['Sensor'], subset['Calibration'], label=f'Data Set {set_num}', color=colors[idx])

# Add vertical blue lines representing standard deviations
for _, row in std_by_sensor.iterrows():
    sensor = row['Sensor']
    std_dev = row['StdDev']
#    ax.plot([sensor, sensor], [-std_dev, std_dev], color='blue', linewidth=1.5)
    ax.errorbar(sensor, 0, yerr=std_dev, fmt='none', ecolor='blue', capsize=5, linewidth=1.5)

# Add gray horizontal lines at ±0.1
ax.axhline(0.1, color='gray', linestyle='--', linewidth=1)
ax.axhline(-0.1, color='gray', linestyle='--', linewidth=1)

# Set axis limits and labels
ax.set_ylim(-0.2, 0.2)
ax.set_xlabel('Sensor Number')
ax.set_ylabel('Calibration Value')
ax.set_title('Calibration Values for Each Sensor Across Three Data Sets')
ax.legend()
plt.grid(True)
plt.tight_layout()
plt.show()