"""Auto-generated Opentrons protocol for Experiment {self.experiment.id}
    Plate labware: {self.plate.opentrons_name}
    """
from opentrons import protocol_api

metadata = {{"apiLevel": "2.14"}}

# user-config from DB
HOLD_TEMP_C = 65
HOLD_DURATION = 30
BUFFER_LOC = "A1"
NS_DENSE_LOC = "A2"
OIL_LOC = ["D1", "D2"]
NS_PREMIX_NUMBER = 10
STOCK_LOCATION = ["B1", "B2", "B3", "B4", "B5", "B6", "C1", "C2"]
MIX_ASPIRATE = 300
MIX_DISPENSE = 300
MIX_CYCLES = 20
MIX_VOL = 150
MIX_Z_MM = 1.0
MIN_SOLUTION_DISPENSE_UL = 10
EMULSION_DISPENSE_UL = 50
SRC_BUFFER_VOL = 150
SRC_NS_VOL = 100
SRC_OIL_VOL = 1300
PLATE_LABWARE = "custom_36_wellplate_35ul"

# precomputed destinations for each stock well
DEST_MAP = {0.125: ["C1", "C2", "C3"],
            0.25: ["C4", "C5", "C6"],
            0.375: ["D1", "D2", "D3"],
            0.5: ["D4", "D5", "D6"],
            0.625: ["E1", "E2", "E3"],
            0.75: ["E4", "E5", "E6"],
            0.875: ["F1", "F2", "F3"],
            1.0: ["F4", "F5", "F6"]}


def run(protocol: protocol_api.ProtocolContext):
    # Load modules
    temperature_module = protocol.load_module("temperatureModuleV1", "10")

    # Load labware
    tip_rack_p20 = protocol.load_labware("opentrons_96_tiprack_20ul", location="2", namespace="opentrons", version=1)
    tip_rack_p300 = protocol.load_labware("opentrons_96_tiprack_300ul", location="5", namespace="opentrons", version=1)
    multiwell_plate = protocol.load_labware(PLATE_LABWARE, location="8")
    aluminum_block = temperature_module.load_labware("opentrons_24_aluminumblock_generic_2ml_screwcap", namespace="opentrons", version=3)

    # Load pipettes
    pipette_right = protocol.load_instrument("{mix_pip}", "right", tip_racks=[tip_rack_p300])
    pipette_left = protocol.load_instrument("{disp_pip}", "left", tip_racks=[tip_rack_p20])

    FRACTIONS = [0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0]

    # Define wells
    buffer_well = aluminum_block.wells_by_name()[BUFFER_LOC]
    ns_dense_well = aluminum_block.wells_by_name()[NS_DENSE_LOC]
    oil_1_well = aluminum_block.wells_by_name()[OIL_LOC[0]]
    oil_2_well = aluminum_block.wells_by_name()[OIL_LOC[1]]
    stock_well = {idx: multiwell_plate.wells_by_name()[x] for idx, x in zip(FRACTIONS, STOCK_LOCATION)}

    # Define liquids (visual grouping only; optional in code-only context)
    LIQUID_VOLUMES = {{
    "buffer_stock_ul": SRC_BUFFER_VOL,
    "ns_dense_stock_ul": SRC_NS_VOL,
    "oil_stock_ul": SRC_OIL_VOL,
    }}

    # Describe liquids (useful when running in simulation / debug)
    protocol.comment("Buffer at " + BUFFER_LOC + ", stock ~" + str(LIQUID_VOLUMES['buffer_stock_ul']) + " uL")
    protocol.comment("NS dense at " + NS_DENSE_LOC + ", stock ~" + str(LIQUID_VOLUMES['ns_dense_stock_ul']) + " uL")
    protocol.comment("Oil_1 at " + OIL_LOC[0] + ", stock ~" + str(LIQUID_VOLUMES['oil_stock_ul']) + " uL")
    protocol.comment("Oil_2 at " + OIL_LOC[1] + ", stock ~" + str(LIQUID_VOLUMES['oil_stock_ul']) + " uL")

    # Heat and hold
    temperature_module.set_temperature(HOLD_TEMP_C)
    protocol.delay(minutes = HOLD_DURATION)

    # Mix NS_Dense (80% of starting volume) with mix pipette
    ns_mix_vol = LIQUID_VOLUMES['ns_dense_stock_ul'] * 0.8
    ns_well = aluminum_block.wells_by_name()[NS_DENSE_LOC]
    pipette_left.pick_up_tip()
    pipette_left.mix(NS_PREMIX_NUMBER, ns_mix_vol, ns_well.bottom(1)) # bottom() parameter = mm from bottom
    pipette_left.blow_out(ns_well.top()) # to avoid unnecesssary concentration error
    # But don't drop tip yet - since about to use in same well

    # Startwith 0.5 at STOCK_LOCATION[3]: 50% Buffer + 50% NS_Dense
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL * 4, ns_well.bottom(2))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL * 4, stock_well[0.5])
    pipette_left.blow_out(stock_well[0.5].top())
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL * 4, buffer_well.bottom(2))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL * 4, stock_well[0.5])
    pipette_left.mix(5, MIN_SOLUTION_DISPENSE_UL * 6, stock_well[0.5].bottom(1))
    pipette_left.blow_out(stock_well[0.5].top())

    # 25% at STOCK_LOCATION[1]: 50% Buffer + 50% 0f 0.5
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL * 2, stock_well[0.5].bottom(1))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL * 2, stock_well[0.25])
    pipette_left.blow_out(stock_well[0.25].top())
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL * 2, buffer_well.bottom(2))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL * 2, stock_well[0.25])
    pipette_left.mix(5, MIN_SOLUTION_DISPENSE_UL * 3, stock_well[0.25].bottom(1))
    pipette_left.blow_out(stock_well[0.25].top())

    # 37.5% at STOCK_LOCATION[2]: 5 uL of 25% + 5 uL of 50%
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL, stock_well[0.25].bottom(1))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL, stock_well[0.375])
    pipette_left.blow_out(stock_well[0.375].top())
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL, stock_well[0.5].bottom(1))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL, stock_well[0.375])
    pipette_left.mix(5, MIN_SOLUTION_DISPENSE_UL * 1.5, stock_well[0.375].bottom(1))

    # 12.5% at STOCK_LOCATION[0]: 5 uL Buffer + 5 uL of 25% - start with buffer with time to dilute any residue
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL, buffer_well.bottom(2))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL, stock_well[0.125])
    pipette_left.blow_out(buffer_well.top())
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL, stock_well[0.25].bottom(1))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL, stock_well[0.125])
    pipette_left.mix(5, MIN_SOLUTION_DISPENSE_UL * 1.5, stock_well[0.125].bottom(1))
    pipette_left.blow_out(stock_well[0.125].top())

    #now change tip to work on higher concentrations
    pipette_left.drop_tip()
    pipette_left.pick_up_tip()

    # 75% at STOCK_LOCATION[5]: 10 uL of 50% + 10 uL NS_Dense
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL * 2, stock_well[0.5].bottom(1))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL * 2, stock_well[0.75])
    pipette_left.blow_out(stock_well[0.75].top())
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL * 2, ns_well.bottom(2))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL * 2, stock_well[0.75])
    pipette_left.mix(5, MIN_SOLUTION_DISPENSE_UL * 3, stock_well[0.75].bottom(1))
    pipette_left.blow_out(stock_well[0.75].top())

    # 62.5% at STOCK_LOCATION[4]: 5 uL of 50% + 5 uL of 75%
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL, stock_well[0.75].bottom(1))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL, stock_well[0.625])
    pipette_left.blow_out(stock_well[0.625].top())
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL, stock_well[0.5].bottom(1))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL, stock_well[0.625])
    pipette_left.mix(5, MIN_SOLUTION_DISPENSE_UL * 1.5, stock_well[0.625].bottom(1))

    # 87.5% at STOCK_LOCATION[6]: 5 uL of 75% + 5 uL of 100%
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL, ns_well.bottom(2))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL, stock_well[0.875])
    pipette_left.blow_out(stock_well[0.875].top())
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL, stock_well[0.75].bottom(1))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL, stock_well[0.875])
    pipette_left.mix(5, MIN_SOLUTION_DISPENSE_UL * 1.5, stock_well[0.875].bottom(1))
    pipette_left.blow_out(stock_well[0.875].top())

    # Finally: 100% in STOCK_LOCATION[7]
    pipette_left.aspirate(MIN_SOLUTION_DISPENSE_UL * 2, ns_well.bottom(2))
    pipette_left.dispense(MIN_SOLUTION_DISPENSE_UL * 2, stock_well[1.0])
    pipette_left.blow_out(stock_well[1.0].top())

    # Keep same tip for all the above as requested
    pipette_left.drop_tip()

    # For each stock: add 200 uL Oil, mix, then distribute FINAL_DISPENSE_UL to destinations
    for stock, dests in DEST_MAP.items():
        # Add oil using mix pipette with new tip
        pipette_right.pick_up_tip()

        if stock <= 0.5:
            pipette_right.aspirate(300, oil_1_well.bottom(2))
        else:
            pipette_right.aspirate(300, oil_2_well.bottom(2))

        pipette_right.dispense(300, stock_well[stock])
        # mix in-place
        pipette_right.flow_rate.aspirate = MIX_ASPIRATE
        pipette_right.flow_rate.dispense = MIX_DISPENSE
        for _ in range(int(MIX_CYCLES)):
            pipette_right.aspirate(MIX_VOL, stock_well[stock].bottom(MIX_Z_MM))
            pipette_right.dispense(MIX_VOL, stock_well[stock].bottom(MIX_Z_MM))

        # Use distribute mode to dispense to all destinations in one go
        dest_wells = [multiwell_plate.wells_by_name()[d] for d in dests]
        pipette_right.distribute(
            EMULSION_DISPENSE_UL,
            stock_well[stock].bottom(1),
            dest_wells,
            new_tip='never',
            disposal_volume=20
        )
        pipette_right.drop_tip()
