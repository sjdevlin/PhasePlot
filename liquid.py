from opentrons.protocol_api import ProtocolContext, labware
import opentrons.execute

class LiquidRobot:
    def __init__(self, name: str, volume: float):
        self.name = name
        self.volume = volume

    def __repr__(self):
        return f"LiquidRobot:(name={self.name}, volume={self.volume})"


def run(protocol: ProtocolContext):
    # Define custom 96-well plate dimensions and layout
    # This creates a fictional 96-well plate with specific dimensions.
    # Adjust these values based on your actual custom plate.
    custom_plate = labware.create(
        "my_custom_96_well_plate",  # A unique name for your custom labware
        grid=(12, 8),               # 12 columns, 8 rows (standard 96-well)
        spacing=(9, 9),             # Spacing between well centers (x, y) in mm
        diameter=6.5,               # Diameter of each well in mm
        depth=10,                   # Depth of each well in mm
        volume=200                  # Maximum volume of each well in microliters
    )

    # Example: Calibrate the custom plate (this assigns it to a deck slot)
    # The 'custom_plate' object is now usable like any other labware.
    protocol.add_labware_definition(custom_plate)
    # Once added, you can load it onto the deck
    plate_on_deck = protocol.load_labware_by_definition(custom_plate, '1', 'my custom plate')

    # Example: Perform a simple transfer using the custom plate
    tiprack = protocol.load_labware('opentrons_96_tiprack_300ul', '10')
    p300 = protocol.load_instrument('p300_single_gen2', 'right', tip_racks=[tiprack])

    p300.pick_up_tip()
    p300.aspirate(100, plate_on_deck.wells_by_name()['A1'])
    p300.dispense(100, plate_on_deck.wells_by_name()['B1'])
    p300.drop_tip()

    protocol.comment(f"Successfully used custom plate: {plate_on_deck.well('A1')}")

# To run this script locally for testing (optional, not for robot execution)
if __name__ == '__main__':
    # This block allows you to test the protocol locally without a robot.
    # It simulates the protocol execution and prints output.
    # This will not actually move robot arms or dispense liquids.
    ctx = opentrons.execute.get_protocol_api('2.15') # Use your Opentrons API version
    ctx.home()
    run(ctx)