"""Provide a graphical interface for microgrid simulations."""

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from ..dispatch.battery import Battery
from .microgrid_simulator import simulate_microgrid_snapshot
from .model_specifications import MicrogridSpecification
from .time_series_graphical_interface import (
    create_time_series_window,
)


def create_application_window() -> tk.Tk:
    """Create the main microgrid simulation window."""

    window = tk.Tk()
    window.title("Microgrid Simulator")
    window.geometry("700x850")

    heading = ttk.Label(
        window,
        text="Manual Operating-Point Test",
        font=("Arial", 20, "bold"),
    )
    heading.pack(
        pady=30,
    )

    description = ttk.Label(
        window,
        text=(
            "Test one electrical operating point. Battery dispatch "
            "is idle unless an advanced manual command is provided."
        ),
    )

    description.pack(
        pady=10,
    )

    form_frame = ttk.LabelFrame(
        window,
        text="Simulation Inputs",
        padding=20,
    )
    form_frame.pack(
        fill="x",
        padx=30,
        pady=20,
    )
    form_frame.columnconfigure(
        1,
        weight=1,
    )

    input_entries = {
        "battery_capacity_kWh": _add_labeled_entry(
            form_frame,
            label_text="Battery capacity (kWh)",
            row=0,
            default_value="20",
        ),
        "battery_energy_kWh": _add_labeled_entry(
            form_frame,
            label_text="Initial battery energy (kWh)",
            row=1,
            default_value="10",
        ),
        "max_charge_kw": _add_labeled_entry(
            form_frame,
            label_text="Maximum charging power (kW)",
            row=2,
            default_value="5",
        ),
        "max_discharge_kw": _add_labeled_entry(
            form_frame,
            label_text="Maximum discharging power (kW)",
            row=3,
            default_value="5",
        ),
        "pv_capacity_kw": _add_labeled_entry(
            form_frame,
            label_text="PV capacity (kW)",
            row=4,
            default_value="30",
        ),
        "load_kw": _add_labeled_entry(
            form_frame,
            label_text="Load Power (kW)",
            row=5,
            default_value="25",
        ),
        "pv_output_kw": _add_labeled_entry(
            form_frame,
            label_text="Current PV output (kW)",
            row=6,
            default_value="10",
        ),
    }

    advanced_frame = ttk.LabelFrame(
        window,
        text="Advanced Snapshot Controls",
        padding=15,
    )

    input_entries["battery_net_injection_kw"] = (
        _add_labeled_entry(
            advanced_frame,
            label_text=(
                "Manual battery command "
                "(+ discharge, - charge)"
            ),
            row=0,
            default_value="0",
        )
    )

    show_advanced = tk.BooleanVar(value=False)

    def toggle_advanced_controls() -> None:
        """Show or hide manual snapshot controls."""

        if show_advanced.get():
            advanced_frame.pack(
                fill="x",
                padx=30,
                pady=10,
                after=form_frame,
            )
        else:
            advanced_frame.pack_forget()

    advanced_checkbox = ttk.Checkbutton(
        window,
        text="Show advanced snapshot controls",
        variable=show_advanced,
        command=toggle_advanced_controls,
    )
    advanced_checkbox.pack(
        pady=5,
        after=form_frame,
    )

    result_frame = ttk.LabelFrame(
        window,
        text="Simulation Results",
        padding=15,
    )

    result_text = ScrolledText(
        result_frame,
        height=14,
        wrap=tk.WORD,
        state="disabled",
        font=("Arial", 14),
    )
    result_text.pack(
        fill="both",
        expand=True,
    )

    _set_result_text(
        result_text,
        "Enter the operating conditions and run the simulation.",
    )

    # This callback runs when the button is clicked.
    def run_simulation() -> None:
        """Run the simulation when the user clicks the button."""

        _set_result_text(
            result_text,
            "Running simulation...",
        )
        result_text.update_idletasks()

        _run_snapshot_from_entries(
            input_entries,
            result_text,
        )

    def reset_inputs() -> None:
        """Restore the default inputs and clear the results."""

        _reset_input_entries(input_entries)
        _set_result_text(
            result_text,
            (
                "Enter the operating conditions and run the simulation."
            ),
        )

    def open_time_series_analysis() -> None:
        """Open the time-series analysis window."""

        create_time_series_window(window)

    button_frame = ttk.Frame(window)
    button_frame.pack(
        pady=10,
    )

    run_button = ttk.Button(
        button_frame,
        text="Run Simulation",
        command=run_simulation,
    )
    run_button.pack(
        side="left",
        padx=5,
    )

    reset_button = ttk.Button(
        button_frame,
        text="Reset Inputs",
        command=reset_inputs,
    )
    reset_button.pack(
        side="left",
        padx=5,
    )

    time_series_button = ttk.Button(
        button_frame,
        text="Time-Series Analysis",
        command=open_time_series_analysis,
    )
    time_series_button.pack(
        side="left",
        padx=5,
    )

    result_frame.pack(
        fill="x",
        padx=30,
        pady=10,
    )

    return window


def _add_labeled_entry(
    parent: tk.Widget,
    *,
    label_text: str,
    row: int,
    default_value: str,
) -> ttk.Entry:
    """Add one labeled input field to a form."""

    label = ttk.Label(
        parent,
        text=label_text,
    )
    label.grid(
        row=row,
        column=0,
        padx=10,
        pady=6,
        sticky="w",
    )

    entry = ttk.Entry(
        parent,
        width=20,
    )
    entry.insert(
        0,
        default_value,
    )
    entry.grid(
        row=row,
        column=1,
        padx=10,
        pady=6,
        sticky="ew",
    )

    return entry


def _reset_input_entries(
    input_entries: dict[str, ttk.Entry],
) -> None:
    """Restore every GUI input field to its default value."""

    default_values = {
        "battery_capacity_kWh": "20",
        "battery_energy_kWh": "10",
        "max_charge_kw": "5",
        "max_discharge_kw": "5",
        "pv_capacity_kw": "30",
        "load_kw": "25",
        "pv_output_kw": "10",
        "battery_net_injection_kw": "0",
    }

    for input_name, default_value in default_values.items():
        entry = input_entries[input_name]
        entry.delete(0, tk.END)
        entry.insert(0, default_value)


def _set_result_text(
    result_text: tk.Text,
    message: str,
) -> None:
    """Replace the text displayed in the results panel."""

    result_text.config(state="normal")
    result_text.delete("1.0", tk.END)
    result_text.insert(tk.END, message)
    result_text.config(state="disabled")


def _run_snapshot_from_entries(
    input_entries: dict[str, ttk.Entry],
    result_text: tk.Text,
) -> None:
    """Run one snapshot using values entered in the GUI."""

    try:
        battery_capacity_kWh = float(
            input_entries["battery_capacity_kWh"].get()
        )
        battery_energy_kWh = float(
            input_entries["battery_energy_kWh"].get()
        )
        max_charge_kw = float(
            input_entries["max_charge_kw"].get()
        )
        max_discharge_kw = float(
            input_entries["max_discharge_kw"].get()
        )
        pv_capacity_kw = float(
            input_entries["pv_capacity_kw"].get()
        )
        load_kw = float(
            input_entries["load_kw"].get()
        )
        pv_output_kw = float(
            input_entries["pv_output_kw"].get()
        )
        battery_net_injection_kw = float(
            input_entries["battery_net_injection_kw"].get()
        )

        battery = Battery(
            capacity_kWh=battery_capacity_kWh,
            energy_kWh=battery_energy_kWh,
            max_charge_kw=max_charge_kw,
            max_discharge_kw=max_discharge_kw,
        )

        specification = MicrogridSpecification(
            battery=battery,
            pv_capacity_kw=pv_capacity_kw,
            load_kw=load_kw,
        )

        # Positive net injection means discharge;
        # negative net injection means charge.
        battery_discharge_kw = max(
            battery_net_injection_kw,
            0.0,
        )
        battery_charge_kw = max(
            -battery_net_injection_kw,
            0.0,
        )

        snapshot = simulate_microgrid_snapshot(
            specification,
            timestamp="2026-08-25 12:00:00",
            pv_output_kw=pv_output_kw,
            battery_charge_kw=battery_charge_kw,
            battery_discharge_kw=battery_discharge_kw,
        )

        result = snapshot.iloc[0]

        _set_result_text(
            result_text,
            (
                "=== Simulation Status ===\n"
                f"Converged: {result['converged']}\n"
                f"Feasible: {result['feasible']}\n"
                "\n"
                "=== Grid Power ===\n"
                "Scheduled net grid import: "
                f"{result['scheduled_grid_import_kw']:.4f} kW\n"
                "PCC net grid import: "
                f"{result['pcc_grid_net_import_kw']:.4f} kW\n"
                "PCC grid import: "
                f"{result['pcc_grid_import_kw']:.4f} kW\n"
                "PCC grid export: "
                f"{result['pcc_grid_export_kw']:.4f} kW\n"
                "Reverse power flow: "
                f"{result['reverse_power_flow']}\n"
                "\n"
                "=== Electrical Conditions ===\n"
                "Minimum voltage: "
                f"{result['minimum_voltage_pu']:.6f} pu\n"
                "Maximum voltage: "
                f"{result['maximum_voltage_pu']:.6f} pu\n"
                "Line loading: "
                f"{result['line_loading_percent']:.4f}%\n"
                "Transformer loading: "
                f"{result['transformer_loading_percent']:.4f}%\n"
                "\n"
                "=== Constraint Checks ===\n"
                "Voltage violation: "
                f"{result['voltage_violation']}\n"
                "Line overload: "
                f"{result['line_overload']}\n"
                "Transformer overload: "
                f"{result['transformer_overload']}"
            ),
        )

    except (TypeError, ValueError) as error:
        messagebox.showerror(
            "Invalid Simulation Input",
            str(error),
        )


def main() -> None:
    """Launch the graphical microgrid simulator."""

    window = create_application_window()
    print("\nSimulator window is open....")
    window.mainloop()


if __name__ == "__main__":
    main()
