import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# -----------------------------------------------------------
# 1. Load the CSV that sits in the same directory as this file
# -----------------------------------------------------------
try:
    # Works when the script is run as a .py file
    csv_path = Path(__file__).with_name("ios.csv")
except NameError:
    # Fallback for interactive / notebook sessions
    csv_path = Path("ios.csv")

df = pd.read_csv(
    csv_path,
    header=None,
    names=["Well", "Minute", "Target", "Actual", "PWM"]  # column labels
)

# -----------------------------------------------------------
# 2. Plot 1 – Well A: target (red) vs actual (blue)
# -----------------------------------------------------------
well_a = df[df["Well"] == "A"]

fig1, ax1 = plt.subplots(figsize=(10, 5))
ax1.plot(well_a["Minute"], well_a["Target"], color="red", label="Target (A)")
ax1.plot(well_a["Minute"], well_a["Actual"], color="blue", label="Actual (A)")

ax1.set_xlabel("Elapsed Minute")
ax1.set_ylabel("Temperature (°C)")
ax1.set_ylim(20, 70)     
ax1.set_title("Well A – Target vs Actual Temperature")
ax1.legend()
ax1.grid(True)
plt.tight_layout()
plt.show()

# -----------------------------------------------------------
# 3. Plot 2 – Wells B, C, D, F: actual temps + target for B
# -----------------------------------------------------------
wells_to_plot = ["B", "C", "D", "E"]
colors_actual = dict(zip(wells_to_plot, ["blue", "green", "orange", "purple"]))

fig2, ax2 = plt.subplots(figsize=(10, 5))

# Actual temperatures for each well
for well in wells_to_plot:
    subset = df[df["Well"] == well]
    ax2.plot(
        subset["Minute"],
        subset["Actual"],
        color=colors_actual[well],
        label=f"Actual ({well})"
    )

# Target temperature for well B in red
well_b = df[df["Well"] == "B"]
ax2.plot(
    well_b["Minute"],
    well_b["Target"],
    color="red",
    linewidth=2,
    label="Target (B)"
)

ax2.set_xlabel("Elapsed Minute")
ax2.set_ylabel("Temperature (°C)")
ax2.set_ylim(20, 70)     
ax2.set_title("Actual Temperatures – Wells B, C, D, E and Target)")
ax2.legend()
ax2.grid(True)
plt.tight_layout()
plt.show()