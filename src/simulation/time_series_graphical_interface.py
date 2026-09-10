"""Provide the time-series microgrid analysis window."""

import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from ..signal_pipeline.region_config import (
    supported_regions,
)


def create_time_series_window(
    parent: tk.Misc,
) -> tk.Toplevel:
    """Create a child window for time-series analysis."""

    window = tk.Toplevel(parent)
    window.title("Microgrid Time-Series Analysis")
    window.geometry("800x850")

    heading = ttk.Label(
        window,
        text="Microgrid Time-Series Analysis",
        font=("Arial", 20, "bold"),
    )
    heading.pack(pady=20)

    description = ttk.Label(
        window,
        text=(
            "Select interval data and configure the time range, "
            "carbon weight, and battery degradation cost."
        ),
    )
    description.pack(pady=5)

    settings_frame = ttk.LabelFrame(
        window,
        text="Analysis Inputs",
        padding=20,
    )
    settings_frame.pack(
        fill="x",
        padx=30,
        pady=20,
    )
    settings_frame.columnconfigure(1, weight=1)

    data_source = tk.StringVar(
        value="Live APIs"
    )

    ttk.Label(
        settings_frame,
        text="Data source",
    ).grid(
        row=0,
        column=0,
        padx=10,
        pady=6,
        sticky="w",
    )

    data_source_combobox = ttk.Combobox(
        settings_frame,
        textvariable=data_source,
        values=(
            "Live APIs",
            "CSV file",
        ),
        state="readonly",
    )
    data_source_combobox.grid(
        row=0,
        column=1,
        columnspan=2,
        padx=10,
        pady=6,
        sticky="ew",
    )

    region_id = tk.StringVar(
        value="caiso_np15"
    )

    ttk.Label(
        settings_frame,
        text="Region",
    ).grid(
        row=1,
        column=0,
        padx=10,
        pady=6,
        sticky="w",
    )

    region_combobox = ttk.Combobox(
        settings_frame,
        textvariable=region_id,
        values=supported_regions(),
        state="readonly",
    )
    region_combobox.grid(
        row=1,
        column=1,
        columnspan=2,
        padx=10,
        pady=6,
        sticky="ew",
    )

    signal_path = tk.StringVar()

    ttk.Label(
        settings_frame,
        text="Signal CSV file",
    ).grid(
        row=2,
        column=0,
        padx=10,
        pady=6,
        sticky="w",
    )

    signal_entry = ttk.Entry(
        settings_frame,
        textvariable=signal_path,
    )
    signal_entry.grid(
        row=2,
        column=1,
        padx=10,
        pady=6,
        sticky="ew",
    )

    def browse_signal_file() -> None:
        """Let the user select a signal CSV file."""

        selected_path = filedialog.askopenfilename(
            parent=window,
            title="Select Time-Series Signal Data",
            filetypes=[
                ("CSV files", "*.csv"),
            ],
        )

        if selected_path:
            signal_path.set(selected_path)

    browse_button = ttk.Button(
        settings_frame,
        text="Browse",
        command=browse_signal_file,
    )
    browse_button.grid(
        row=2,
        column=2,
        padx=10,
        pady=6,
    )

    setting_entries = {
        "start_date": _add_setting_entry(
            settings_frame,
            label_text="Start date (YYYY-MM-DD)",
            row=3,
            default_value="2026-08-25",
        ),
        "number_of_days": _add_setting_entry(
            settings_frame,
            label_text="Number of days",
            row=4,
            default_value="2",
        ),
        "timestep_minutes": _add_setting_entry(
            settings_frame,
            label_text="Timestep (minutes)",
            row=5,
            default_value="15",
        ),
        "carbon_weight": _add_setting_entry(
            settings_frame,
            label_text="Carbon weight ($/kgCO2)",
            row=6,
            default_value="0.20",
        ),
        "degradation_cost_per_kWh": _add_setting_entry(
            settings_frame,
            label_text="Battery degradation cost ($/kWh)",
            row=7,
            default_value="0.03",
        ),
    }

    strategy_frame = ttk.LabelFrame(
        window,
        text="Optimization Strategies",
        padding=15,
    )
    strategy_frame.pack(
        fill="x",
        padx=30,
        pady=10,
    )

    strategy_labels = {
        "no_battery": "No-battery baseline",
        "rule_based": "Rule-based dispatch",
        "cost_optimal": "Cost optimization",
        "carbon_optimal": "Carbon optimization",
        "combined_optimal": "Combined optimization",
    }

    strategy_variables = {}

    for row, (
        strategy_name,
        display_label,
    ) in enumerate(strategy_labels.items()):
        selected = tk.BooleanVar(value=True)

        strategy_variables[strategy_name] = selected

        strategy_checkbox = ttk.Checkbutton(
            strategy_frame,
            text=display_label,
            variable=selected,
        )
        strategy_checkbox.grid(
            row=row,
            column=0,
            sticky="w",
            padx=10,
            pady=3,
        )

        if strategy_name == "no_battery":
            strategy_checkbox.config(
                state="disabled",
            )

    result_text = ScrolledText(
        window,
        height=16,
        wrap=tk.WORD,
        state="disabled",
        font=("Arial", 14),
    )
    result_text.pack(
        fill="both",
        expand=True,
        padx=30,
        pady=20,
    )

    _set_result_text(
        result_text,
        (
            "Select a signal CSV file. The next implementation "
            "will connect these settings to the analysis backend."
        ),
    )

    return window


def _add_setting_entry(
    parent: tk.Widget,
    *,
    label_text: str,
    row: int,
    default_value: str,
) -> ttk.Entry:
    """Add one labeled time-series setting."""

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

    entry = ttk.Entry(parent)
    entry.insert(0, default_value)
    entry.grid(
        row=row,
        column=1,
        columnspan=2,
        padx=10,
        pady=6,
        sticky="ew",
    )

    return entry


def _set_result_text(
    result_text: tk.Text,
    message: str,
) -> None:
    """Replace the time-series result text."""

    result_text.config(state="normal")
    result_text.delete("1.0", tk.END)
    result_text.insert(tk.END, message)
    result_text.config(state="disabled")
