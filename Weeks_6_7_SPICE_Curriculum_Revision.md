# Weeks 6-7 SPICE Curriculum Revision

## Purpose of This Revision

The original curriculum introduces SPICE fundamentals in Week 6 and studies a buck converter in Week 7. The revised curriculum keeps the buck converter as the first switching-converter reference, then expands the study to additional converter topologies and grid-related electrical components.

The goal is not only to make individual simulations run. For every circuit, the learner should be able to:

1. Describe the physical purpose of the circuit.
2. Predict its important voltage and current behavior.
3. Calculate an ideal or approximate result by hand.
4. Configure an appropriate SPICE analysis.
5. Compare the simulation with the calculation.
6. Explain differences caused by losses, parasitic effects, switching, or modeling assumptions.

## Scope and Terminology

A power-electronic converter uses semiconductor switching devices to change the form or level of electrical power. Examples include buck converters, boost converters, rectifiers, and inverters.

A transformer is not a switched power-electronic converter. It transfers AC power magnetically and changes voltage and current according to its turns ratio. It is included because transformers are essential grid components and also provide isolation and energy transfer in converter topologies such as the flyback converter.

## Common Study Method

Each new circuit or technology will be studied through the same sequence so that breadth does not replace depth:

1. Identify its function in an energy or grid system.
2. Draw the power path and predict voltage and current directions.
3. Derive the main ideal relationship by hand.
4. Simulate a simple ideal model and verify the relationship.
5. Introduce selected non-ideal behavior such as resistance, diode drop, leakage, or switching loss.
6. Sweep meaningful parameters and explain the resulting trends.
7. Record component stress, ripple, losses, efficiency trends, and model limitations.

The comparison will use consistent questions across technologies:

- Does the circuit convert AC or DC, and what form appears at its output?
- Can it step voltage up, step voltage down, or do both?
- Does it provide galvanic isolation?
- Where is energy temporarily stored?
- Which components carry the highest current or block the highest voltage?
- What creates ripple, harmonics, losses, and transient stress?
- What grid or DER application is the circuit suited for?
- Which behavior belongs in SPICE, OpenDSS, or a control-system model?

## Week 6 - SPICE Foundations Through Practical Circuits

### Weekly objective

Build enough SPICE and circuit-analysis knowledge to predict, simulate, and explain passive circuits, transformers, rectifiers, and an introductory buck converter.

### Session 1 - SPICE workflow and analytical foundations

- Learn schematic and netlist concepts.
- Define nodes and the reference node, or ground.
- Place voltage sources, current sources, resistors, capacitors, and inductors.
- Measure voltage, current, and power with consistent sign conventions.
- Use DC operating-point, transient, AC-sweep, and parameter-sweep analyses.
- Verify a resistive divider against Ohm's law and Kirchhoff's laws.

### Session 2 - RC, RL, and RLC behavior

- Simulate capacitor charging and discharging.
- Simulate inductor-current rise and decay.
- Relate RC and RL time constants to transient plots.
- Examine RLC resonance and damping.
- Use an AC sweep to study gain, phase, cutoff frequency, and resonance.

### Session 3 - Transformer fundamentals

- Model an ideal transformer using coupled inductors.
- Relate turns ratio to voltage ratio and current ratio.
- Study magnetizing current, coupling coefficient, leakage inductance, and load regulation.
- Compare no-load and loaded behavior.
- Treat core saturation and hysteresis as advanced model limitations unless a suitable nonlinear core model is available.

### Session 4 - AC-to-DC rectification

- Compare half-wave and full-wave diode rectifiers.
- Add a smoothing capacitor and observe DC ripple.
- Vary load resistance, capacitance, and input frequency.
- Explain diode voltage drop, charging pulses, inrush current, and ripple tradeoffs.

### Session 5 - Buck converter as the switching reference

- Introduce switches, diodes, pulse-width modulation, duty cycle, and switching frequency.
- Build an ideal buck converter.
- Verify the ideal relationship between input voltage, duty cycle, and average output voltage.
- Observe inductor-current ripple, output-voltage ripple, and startup transient behavior.
- Establish a common set of measurements for comparing later converters.

### Week 6 deliverable

A verified SPICE study containing passive-circuit, transformer, rectifier, and buck-converter simulations. Each simulation includes a hand calculation, labeled plots, a physical explanation, and documented assumptions.

## Week 7 - Converter Families and Grid Interfaces

### Weekly objective

Compare several converter technologies and connect their device-level behavior to photovoltaic, battery, and grid interfaces.

### Session 1 - Buck converter with non-ideal components

- Replace ideal switches with practical diode and MOSFET models where appropriate.
- Examine conduction loss, switching loss trends, ripple, and efficiency.
- Sweep load, inductance, capacitance, duty cycle, and switching frequency.
- Compare ideal equations with non-ideal simulation results.

### Session 2 - Boost and buck-boost converters

- Build a boost converter and verify its ideal conversion ratio.
- Build an inverting buck-boost converter and examine output polarity.
- Compare switch stress, diode stress, current ripple, voltage ripple, and useful operating ranges.
- Relate these converters to PV and battery DC-bus applications.

### Session 3 - Isolated DC-DC conversion

- Introduce galvanic isolation and high-frequency magnetic components.
- Build a simplified flyback converter using coupled inductors.
- Examine turns ratio, duty cycle, magnetizing current, leakage effects, and switch-voltage stress.
- Compare the flyback transformer's energy-storage role with a conventional grid transformer's power-transfer role.

### Session 4 - DC-to-AC inversion

- Build a single-phase half-bridge or H-bridge inverter.
- Generate a square-wave output before introducing sinusoidal PWM.
- Measure fundamental voltage, switching ripple, and harmonic content.
- Relate the inverter to battery-energy-storage and PV grid interfaces.

### Session 5 - Filters and simplified grid connection

- Add LC and introductory LCL filters to an inverter output.
- Represent the grid as an AC source with source and line impedance.
- Include a simplified transformer and load at the point of connection.
- Observe filter resonance, current ripple, voltage drop, and sensitivity to grid impedance.
- Clearly distinguish an open-loop grid-interface circuit from a production grid-following inverter with synchronization and closed-loop current control.

### Session 6 - Comparative engineering study

- Compare buck, boost, buck-boost, flyback, rectifier, and inverter behavior.
- Summarize input/output form, isolation, voltage-conversion range, device stress, ripple, efficiency trends, and common applications.
- Identify which behavior belongs in SPICE, which belongs in OpenDSS, and which requires a control-system model.
- Document model limitations and propose later improvements such as thermal models, nonlinear magnetics, device datasheet models, feedback control, and three-phase conversion.

### Week 7 deliverable

A comparative converter and grid-interface report supported by verified SPICE simulations, parameter sweeps, analytical checks, and explanations of physical behavior and model limitations.

## Connection to the Existing Microgrid Project

The revised SPICE study complements rather than replaces the OpenDSS model:

- OpenDSS evaluates feeder voltage, power flow, equipment loading, losses, and reverse power flow over operational schedules.
- SPICE evaluates circuit transients, switching waveforms, ripple, component stress, filtering, and simplified converter behavior.
- The Python optimizer determines when the battery should charge or discharge.
- A real converter and controller determine how that requested power is physically produced.

The eventual project architecture can therefore be understood at three levels:

1. Dispatch and control level: Python optimization and future rolling control.
2. Distribution-system level: OpenDSS feeder and grid constraints.
3. Component and switching level: SPICE converters, magnetics, filters, and device behavior.

## Topics Reserved for Later Development

The following topics are valuable but should not be required for completing Weeks 6-7:

- Closed-loop voltage and current control
- Phase-locked loops and grid synchronization
- Three-phase two-level and multilevel inverters
- Power-factor correction
- Detailed semiconductor switching and thermal-loss models
- Nonlinear transformer saturation and hysteresis
- Electromagnetic-interference filter design
- Fault behavior and protection coordination
- Hardware-in-the-loop or controller-in-the-loop simulation

These extensions can be introduced after the learner can confidently predict and explain the simpler converter models.
