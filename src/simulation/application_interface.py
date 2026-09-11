"""Provide the guided desktop workflow for a complete microgrid study."""

from datetime import date
from decimal import Decimal, InvalidOperation
import multiprocessing
import queue
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..signal_pipeline.price_sources import PRICE_MODES
from ..signal_pipeline.region_config import (
    get_region_config,
    supported_regions,
)
from ..dispatch.battery import Battery
from .interface_analysis import (
    build_analysis_details,
    build_results_table,
    InterfaceAnalysisResult,
    run_integrated_csv_analysis,
    run_live_api_analysis,
)
from .model_specifications import MicrogridSpecification


STRATEGY_LABELS = {
    "no_battery": "No-battery baseline",
    "rule_based": "Rule-based dispatch",
    "cost_optimal": "Cost optimization",
    "carbon_optimal": "Carbon optimization",
    "combined_optimal": "Combined optimization",
}

PRICE_MODE_LABELS = {
    "wholesale_market": "Wholesale market price",
    "fixed_retail": "Fixed retail price",
    "time_of_use": "Time-of-use retail tariff",
    "csv": "Price supplied by CSV",
}


class MicrogridApplication:
    """Own one root window and switch between the study workflow pages."""

    def __init__(self, window: tk.Tk) -> None:
        self.window = window
        self.window.title("Microgrid Analysis")
        self.window.geometry("900x850")
        self.window.minsize(780, 700)

        self.values = self._create_variables()
        self.strategy_values = {
            name: tk.BooleanVar(value=True)
            for name in STRATEGY_LABELS
        }
        self.pages: dict[str, ttk.Frame] = {}
        self.battery_entries: list[ttk.Entry] = []
        self.analysis_result: InterfaceAnalysisResult | None = None
        self.process_context = multiprocessing.get_context("spawn")
        self.analysis_messages = self.process_context.Queue()
        self.analysis_process: multiprocessing.Process | None = None
        self.worker_exit_empty_polls = 0
        self.analysis_started_at: float | None = None
        self.is_closing = False
        self.window.protocol(
            "WM_DELETE_WINDOW",
            self._close_application,
        )

        self._build_header()

        self.page_container = ttk.Frame(window, padding=(30, 10, 30, 20))
        self.page_container.pack(fill="both", expand=True)
        self.page_container.rowconfigure(0, weight=1)
        self.page_container.columnconfigure(0, weight=1)

        self._build_analysis_page()
        self._build_microgrid_page()
        self._build_review_page()
        self._build_results_page()

        self.show_page("analysis")

    def _create_variables(self) -> dict[str, tk.Variable]:
        """Create shared variables so page values survive navigation."""

        first_region = supported_regions()[0]
        region = get_region_config(first_region)

        return {
            "source_mode": tk.StringVar(value="live_api"),
            "region_id": tk.StringVar(value=first_region),
            "signal_csv_path": tk.StringVar(),
            "start_date": tk.StringVar(value="2026-08-25"),
            "end_date_inclusive": tk.StringVar(value="2026-08-26"),
            "timestep_minutes": tk.StringVar(value="15"),
            "price_mode": tk.StringVar(value="wholesale_market"),
            "fixed_retail_price": tk.StringVar(value="0.20"),
            "price_csv_path": tk.StringVar(),
            "market_provider": tk.StringVar(value=region.market_provider),
            "market_location": tk.StringVar(value=region.market_location),
            "carbon_provider": tk.StringVar(value=region.carbon_provider),
            "carbon_zone": tk.StringVar(value=region.carbon_zone),
            "timezone": tk.StringVar(value=region.timezone),
            "carbon_weight_mode": tk.StringVar(value="single"),
            "carbon_weight_single": tk.StringVar(value="0.20"),
            "carbon_weight_list": tk.StringVar(value="0.00, 0.10, 0.20"),
            "carbon_weight_start": tk.StringVar(value="0.00"),
            "carbon_weight_end": tk.StringVar(value="0.50"),
            "carbon_weight_interval": tk.StringVar(value="0.10"),
            "degradation_cost": tk.StringVar(value="0.03"),
            "battery_capacity": tk.StringVar(value="20"),
            "battery_initial_energy": tk.StringVar(value="10"),
            "battery_max_charge": tk.StringVar(value="5"),
            "battery_max_discharge": tk.StringVar(value="5"),
            "pv_capacity": tk.StringVar(value="30"),
            "load_power": tk.StringVar(value="25"),
        }

    def _build_header(self) -> None:
        header = ttk.Frame(self.window, padding=(30, 22, 30, 8))
        header.pack(fill="x")

        ttk.Label(
            header,
            text="Microgrid Analysis",
            font=("Arial", 22, "bold"),
        ).pack(side="left")

    def _new_page(self, name: str) -> ttk.Frame:
        page = ttk.Frame(self.page_container)
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[name] = page
        return page

    @staticmethod
    def _page_title(
        page: ttk.Frame,
        step: str,
        title: str,
        description: str,
    ) -> None:
        ttk.Label(
            page,
            text=f"{step}  {title}",
            font=("Arial", 19, "bold"),
        ).pack(anchor="w", pady=(5, 6))
        ttk.Label(page, text=description, wraplength=800).pack(
            anchor="w",
            pady=(0, 18),
        )

    def _build_analysis_page(self) -> None:
        page = self._new_page("analysis")
        self._page_title(
            page,
            "1 of 4",
            "Analysis Setup",
            "Choose the study horizon, data sources, pricing model, and optimization strategies.",
        )

        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True)

        source_tab = ttk.Frame(notebook, padding=18)
        strategy_tab = ttk.Frame(notebook, padding=18)
        notebook.add(source_tab, text="Data and time range")
        notebook.add(strategy_tab, text="Strategies and costs")

        source_tab.columnconfigure(1, weight=1)
        self._add_combobox(
            source_tab,
            "Data source",
            self.values["source_mode"],
            ("live_api", "integrated_csv"),
            0,
        ).bind("<<ComboboxSelected>>", self._update_source_controls)

        self.region_combobox = self._add_combobox(
            source_tab,
            "Live API region",
            self.values["region_id"],
            tuple(supported_regions()),
            1,
        )
        self.region_combobox.bind("<<ComboboxSelected>>", self._apply_region_defaults)

        self.signal_csv_entry, self.signal_csv_button = self._add_file_row(
            source_tab,
            "Integrated signal CSV",
            self.values["signal_csv_path"],
            2,
        )

        self._add_entry(source_tab, "Start date (YYYY-MM-DD)", "start_date", 3)
        self._add_entry(
            source_tab,
            "End date, inclusive (YYYY-MM-DD)",
            "end_date_inclusive",
            4,
        )
        self._add_entry(source_tab, "Timestep (minutes)", "timestep_minutes", 5)

        self.price_mode_combobox = self._add_combobox(
            source_tab,
            "Electricity price model",
            self.values["price_mode"],
            tuple(PRICE_MODES),
            6,
        )
        self.price_mode_combobox.bind("<<ComboboxSelected>>", self._update_price_controls)

        self.fixed_price_entry = self._add_entry(
            source_tab,
            "Fixed retail price ($/kWh)",
            "fixed_retail_price",
            7,
        )
        self.price_csv_entry, self.price_csv_button = self._add_file_row(
            source_tab,
            "Price CSV",
            self.values["price_csv_path"],
            8,
        )

        self.show_overrides = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            source_tab,
            text="Show advanced provider overrides",
            variable=self.show_overrides,
            command=self._toggle_overrides,
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(14, 5))

        self.override_frame = ttk.LabelFrame(
            source_tab,
            text="Advanced provider overrides",
            padding=12,
        )
        self.override_frame.columnconfigure(1, weight=1)
        self._add_entry(self.override_frame, "Market provider", "market_provider", 0)
        self._add_entry(self.override_frame, "Price node or hub", "market_location", 1)
        self._add_entry(self.override_frame, "Carbon provider", "carbon_provider", 2)
        self._add_entry(self.override_frame, "Carbon zone", "carbon_zone", 3)
        self._add_entry(self.override_frame, "Timezone", "timezone", 4)

        strategy_tab.columnconfigure(1, weight=1)
        ttk.Label(
            strategy_tab,
            text="Selected dispatch scenarios",
            font=("Arial", 14, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        for row, (name, label) in enumerate(STRATEGY_LABELS.items(), start=1):
            checkbox = ttk.Checkbutton(
                strategy_tab,
                text=label,
                variable=self.strategy_values[name],
                command=self._update_battery_controls,
            )
            checkbox.grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
            if name == "no_battery":
                checkbox.configure(state="disabled")

        self._add_entry(
            strategy_tab,
            "Battery degradation cost ($/kWh throughput)",
            "degradation_cost",
            7,
        )

        self.weight_mode_combobox = self._add_combobox(
            strategy_tab,
            "Combined carbon-weight input",
            self.values["carbon_weight_mode"],
            ("single", "list", "range"),
            8,
        )
        self.weight_mode_combobox.bind("<<ComboboxSelected>>", self._update_weight_controls)

        self.weight_entries = {
            "single": self._add_entry(
                strategy_tab,
                "Single weight ($/kgCO2)",
                "carbon_weight_single",
                9,
            ),
            "list": self._add_entry(
                strategy_tab,
                "Weight list (comma-separated)",
                "carbon_weight_list",
                10,
            ),
            "range_start": self._add_entry(
                strategy_tab,
                "Range start",
                "carbon_weight_start",
                11,
            ),
            "range_end": self._add_entry(
                strategy_tab,
                "Range end (inclusive)",
                "carbon_weight_end",
                12,
            ),
            "range_interval": self._add_entry(
                strategy_tab,
                "Range interval",
                "carbon_weight_interval",
                13,
            ),
        }

        self._navigation(page, next_page="microgrid")
        self._update_source_controls()
        self._update_price_controls()
        self._update_weight_controls()

    def _build_microgrid_page(self) -> None:
        page = self._new_page("microgrid")
        self._page_title(
            page,
            "2 of 4",
            "Microgrid Configuration",
            "Define the installed battery, PV capacity, and load assumptions used by the study.",
        )

        battery_frame = ttk.LabelFrame(page, text="Battery", padding=18)
        battery_frame.pack(fill="x", pady=8)
        battery_frame.columnconfigure(1, weight=1)

        self.battery_status = ttk.Label(battery_frame, text="")
        self.battery_status.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        for row, (label, name) in enumerate(
            (
                ("Usable capacity (kWh)", "battery_capacity"),
                ("Initial stored energy (kWh)", "battery_initial_energy"),
                ("Maximum charging power (kW)", "battery_max_charge"),
                ("Maximum discharging power (kW)", "battery_max_discharge"),
            ),
            start=1,
        ):
            self.battery_entries.append(self._add_entry(battery_frame, label, name, row))

        system_frame = ttk.LabelFrame(page, text="PV and load", padding=18)
        system_frame.pack(fill="x", pady=12)
        system_frame.columnconfigure(1, weight=1)
        self._add_entry(system_frame, "Rated PV capacity (kW)", "pv_capacity", 0)
        self._add_entry(system_frame, "Constant or target load (kW)", "load_power", 1)

        ttk.Label(
            system_frame,
            text=(
                "Profile import and scaling rules will be designed after the guided interface "
                "workflow is complete."
            ),
            wraplength=760,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

        self._navigation(page, previous_page="analysis", next_page="review")
        self._update_battery_controls()

    def _build_review_page(self) -> None:
        page = self._new_page("review")
        self._page_title(
            page,
            "3 of 4",
            "Review and Run",
            "Confirm the complete study request before data retrieval and simulation begin.",
        )

        review_container = ttk.Frame(page)
        review_container.pack(fill="both", expand=True, pady=8)

        self.review_canvas = tk.Canvas(
            review_container,
            highlightthickness=0,
        )
        self.review_canvas.grid(row=0, column=0, sticky="nsew")

        review_vertical_scrollbar = ttk.Scrollbar(
            review_container,
            orient="vertical",
            command=self.review_canvas.yview,
        )
        review_vertical_scrollbar.grid(row=0, column=1, sticky="ns")

        review_horizontal_scrollbar = ttk.Scrollbar(
            review_container,
            orient="horizontal",
            command=self.review_canvas.xview,
        )
        review_horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

        review_container.rowconfigure(0, weight=1)
        review_container.columnconfigure(0, weight=1)
        self.review_canvas.configure(
            yscrollcommand=review_vertical_scrollbar.set,
            xscrollcommand=review_horizontal_scrollbar.set,
        )

        self.review_table_frame = tk.Frame(self.review_canvas)
        self.review_canvas.create_window(
            (0, 0),
            window=self.review_table_frame,
            anchor="nw",
        )
        self.review_table_frame.bind(
            "<Configure>",
            lambda _event: self.review_canvas.configure(
                scrollregion=self.review_canvas.bbox("all")
            ),
        )

        controls = ttk.Frame(page)
        controls.pack(fill="x", pady=(12, 0))
        ttk.Button(controls, text="Back", command=lambda: self.show_page("microgrid")).pack(side="left")
        self.run_analysis_button = ttk.Button(
            controls,
            text="Run Analysis",
            command=self._validate_and_run_analysis,
        )
        self.run_analysis_button.pack(side="right")

    def _build_results_page(self) -> None:
        page = self._new_page("results")
        self._page_title(
            page,
            "4 of 4",
            "Results",
            "The completed workflow will provide visual comparisons and downloadable CSV outputs here.",
        )

        details_frame = ttk.LabelFrame(
            page,
            text="Analysis details",
            padding=14,
        )
        details_frame.pack(fill="x", pady=(4, 8))
        details_frame.columnconfigure(1, weight=1)

        self.analysis_detail_values: dict[str, tk.StringVar] = {}

        for row, label in enumerate(
            ("Data source", "Location", "Time range", "Time interval")
        ):
            ttk.Label(
                details_frame,
                text=f"{label}:",
                font=("Arial", 11, "bold"),
            ).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=3)

            value = tk.StringVar(value="—")
            self.analysis_detail_values[label] = value
            ttk.Label(
                details_frame,
                textvariable=value,
                wraplength=680,
            ).grid(row=row, column=1, sticky="w", pady=3)

        output_frame = ttk.LabelFrame(page, text="Analysis output", padding=18)
        output_frame.pack(fill="both", expand=True, pady=10)

        self.progress_message = tk.StringVar(
            value="Run the analysis from the Review and Run page."
        )
        ttk.Label(
            output_frame,
            textvariable=self.progress_message,
            font=("Arial", 13, "bold"),
            wraplength=760,
        ).pack(anchor="w", pady=(0, 10))

        self.analysis_progress = ttk.Progressbar(
            output_frame,
            mode="determinate",
            maximum=100,
        )
        self.analysis_progress.pack(fill="x", pady=(0, 8))

        self.elapsed_message = tk.StringVar(value="Elapsed time: —")
        ttk.Label(
            output_frame,
            textvariable=self.elapsed_message,
        ).pack(anchor="w", pady=(0, 8))

        self.result_message = ttk.Label(
            output_frame,
            text="No results to display yet.",
            wraplength=760,
        )
        self.result_message.pack(anchor="w", pady=(5, 10))

        table_container = ttk.Frame(output_frame)
        table_container.pack(fill="both", expand=True)
        table_container.rowconfigure(0, weight=1)
        table_container.columnconfigure(0, weight=1)

        self.table_canvas = tk.Canvas(
            table_container,
            height=100,
            highlightthickness=0,
        )
        self.table_canvas.grid(row=0, column=0, sticky="nsew")

        self.table_scrollbar = ttk.Scrollbar(
            table_container,
            orient="horizontal",
            command=self.table_canvas.xview,
        )
        self.table_scrollbar.grid(row=1, column=0, sticky="ew")

        self.table_vertical_scrollbar = ttk.Scrollbar(
            table_container,
            orient="vertical",
            command=self.table_canvas.yview,
        )
        self.table_vertical_scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.table_canvas.configure(
            xscrollcommand=self.table_scrollbar.set,
            yscrollcommand=self.table_vertical_scrollbar.set,
        )

        self.table_frame = tk.Frame(self.table_canvas)
        self.table_window = self.table_canvas.create_window(
            (0, 0),
            window=self.table_frame,
            anchor="nw",
        )
        self.table_frame.bind(
            "<Configure>",
            self._update_table_scroll_region,
        )
        self._bind_result_table_scrolling(self.table_canvas)
        self._bind_result_table_scrolling(self.table_frame)

        self._navigation(page, previous_page="review")

    def _navigation(
        self,
        page: ttk.Frame,
        *,
        previous_page: str | None = None,
        next_page: str | None = None,
    ) -> None:
        controls = ttk.Frame(page)
        controls.pack(fill="x", pady=(16, 0))
        if previous_page:
            ttk.Button(
                controls,
                text="Back",
                command=lambda: self.show_page(previous_page),
            ).pack(side="left")
        if next_page:
            ttk.Button(
                controls,
                text="Next",
                command=lambda: self.show_page(next_page),
            ).pack(side="right")

    def show_page(self, name: str) -> None:
        """Raise one workflow page while retaining all shared values."""

        if name == "review":
            self._refresh_review()
        self.pages[name].tkraise()

    def _add_entry(
        self,
        parent: ttk.Frame,
        label: str,
        variable_name: str,
        row: int,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=5)
        entry = ttk.Entry(parent, textvariable=self.values[variable_name])
        entry.grid(row=row, column=1, sticky="ew", padx=6, pady=5)
        return entry

    def _add_combobox(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.Variable,
        options: tuple[str, ...],
        row: int,
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=5)
        combobox = ttk.Combobox(parent, textvariable=variable, values=options, state="readonly")
        combobox.grid(row=row, column=1, columnspan=2, sticky="ew", padx=6, pady=5)
        return combobox

    def _add_file_row(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.Variable,
        row: int,
    ) -> tuple[ttk.Entry, ttk.Button]:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=6, pady=5)
        button = ttk.Button(
            parent,
            text="Browse",
            command=lambda: self._browse_csv(variable),
        )
        button.grid(row=row, column=2, padx=6, pady=5)
        return entry, button

    def _browse_csv(self, variable: tk.Variable) -> None:
        path = filedialog.askopenfilename(
            parent=self.window,
            title="Select CSV file",
            filetypes=[("CSV files", "*.csv")],
        )
        if path:
            variable.set(path)

    def _apply_region_defaults(self, _event=None) -> None:
        region = get_region_config(str(self.values["region_id"].get()))
        self.values["market_provider"].set(region.market_provider)
        self.values["market_location"].set(region.market_location)
        self.values["carbon_provider"].set(region.carbon_provider)
        self.values["carbon_zone"].set(region.carbon_zone)
        self.values["timezone"].set(region.timezone)

    def _update_source_controls(self, _event=None) -> None:
        live = self.values["source_mode"].get() == "live_api"
        self.region_combobox.configure(state="readonly" if live else "disabled")
        self.price_mode_combobox.configure(state="readonly" if live else "disabled")
        csv_state = "disabled" if live else "normal"
        self.signal_csv_entry.configure(state=csv_state)
        self.signal_csv_button.configure(state=csv_state)
        self._update_price_controls()

    def _update_price_controls(self, _event=None) -> None:
        live = self.values["source_mode"].get() == "live_api"
        mode = self.values["price_mode"].get()
        self.fixed_price_entry.configure(
            state="normal" if live and mode == "fixed_retail" else "disabled"
        )
        csv_state = "normal" if live and mode == "csv" else "disabled"
        self.price_csv_entry.configure(state=csv_state)
        self.price_csv_button.configure(state=csv_state)

    def _toggle_overrides(self) -> None:
        if self.show_overrides.get():
            self.override_frame.grid(row=10, column=0, columnspan=3, sticky="ew", pady=8)
        else:
            self.override_frame.grid_forget()

    def _update_weight_controls(self, _event=None) -> None:
        mode = self.values["carbon_weight_mode"].get()
        for key, entry in self.weight_entries.items():
            active = key == mode or (mode == "range" and key.startswith("range_"))
            entry.configure(state="normal" if active else "disabled")

    def _update_battery_controls(self) -> None:
        enabled = any(
            variable.get()
            for name, variable in self.strategy_values.items()
            if name != "no_battery"
        )
        state = "normal" if enabled else "disabled"
        for entry in self.battery_entries:
            entry.configure(state=state)
        self.battery_status.configure(
            text=(
                "Battery parameters are active."
                if enabled
                else "Only the no-battery baseline is selected; battery inputs will be ignored."
            )
        )

    def _refresh_review(self) -> None:
        try:
            weights = parse_carbon_weights(
                str(self.values["carbon_weight_mode"].get()),
                single=str(self.values["carbon_weight_single"].get()),
                explicit_list=str(self.values["carbon_weight_list"].get()),
                range_start=str(self.values["carbon_weight_start"].get()),
                range_end=str(self.values["carbon_weight_end"].get()),
                range_interval=str(self.values["carbon_weight_interval"].get()),
            )
        except ValueError as error:
            weights = [f"Invalid: {error}"]

        strategies = selected_strategies(self.strategy_values)
        source_mode = str(self.values["source_mode"].get())
        battery_active = any(name != "no_battery" for name in strategies)

        rows = build_review_rows(
            source_mode=source_mode,
            region_id=str(self.values["region_id"].get()),
            start_date=str(self.values["start_date"].get()),
            end_date_inclusive=str(self.values["end_date_inclusive"].get()),
            timestep_minutes=str(self.values["timestep_minutes"].get()),
            price_mode=str(self.values["price_mode"].get()),
            strategies=strategies,
            carbon_weights=tuple(map(str, weights)),
            degradation_cost=str(self.values["degradation_cost"].get()),
            battery_active=battery_active,
            battery_capacity=str(self.values["battery_capacity"].get()),
            battery_initial_energy=str(self.values["battery_initial_energy"].get()),
            battery_max_charge=str(self.values["battery_max_charge"].get()),
            battery_max_discharge=str(self.values["battery_max_discharge"].get()),
            pv_capacity=str(self.values["pv_capacity"].get()),
            load_power=str(self.values["load_power"].get()),
        )
        self._render_review_table(rows)

    def _render_review_table(
        self,
        rows: tuple[tuple[str, str, str], ...],
    ) -> None:
        """Render the review settings as explicitly bordered cells."""

        for child in self.review_table_frame.winfo_children():
            child.destroy()

        headings = ("Section", "Setting", "Selected value")

        for column_index, heading in enumerate(headings):
            tk.Label(
                self.review_table_frame,
                text=heading,
                font=("Arial", 12, "bold"),
                background="#d9e3f0",
                relief="solid",
                borderwidth=1,
                padx=12,
                pady=8,
            ).grid(row=0, column=column_index, sticky="nsew")

        for row_index, row_values in enumerate(rows, start=1):
            background = "#ffffff" if row_index % 2 else "#f3f6f9"

            for column_index, value in enumerate(row_values):
                font = (
                    ("Arial", 11, "bold")
                    if column_index == 0
                    else ("Arial", 11)
                )
                tk.Label(
                    self.review_table_frame,
                    text=value,
                    font=font,
                    background=background,
                    relief="solid",
                    borderwidth=1,
                    padx=12,
                    pady=7,
                    anchor="w",
                    justify="left",
                ).grid(row=row_index, column=column_index, sticky="nsew")

        self.review_table_frame.update_idletasks()
        self.review_canvas.configure(
            scrollregion=self.review_canvas.bbox("all")
        )

    def _validate_and_run_analysis(self) -> None:
        """Validate the form and start CSV analysis outside the GUI thread."""

        try:
            days = calculate_inclusive_day_count(
                str(self.values["start_date"].get()),
                str(self.values["end_date_inclusive"].get()),
            )
            timestep = int(str(self.values["timestep_minutes"].get()))
            if timestep <= 0:
                raise ValueError("Timestep must be positive.")
            weights = parse_carbon_weights(
                str(self.values["carbon_weight_mode"].get()),
                single=str(self.values["carbon_weight_single"].get()),
                explicit_list=str(self.values["carbon_weight_list"].get()),
                range_start=str(self.values["carbon_weight_start"].get()),
                range_end=str(self.values["carbon_weight_end"].get()),
                range_interval=str(self.values["carbon_weight_interval"].get()),
            )
            if self.values["source_mode"].get() == "integrated_csv" and not self.values["signal_csv_path"].get():
                raise ValueError("Select an integrated signal CSV file.")

            strategies = selected_strategies(self.strategy_values)

            if not any(name != "no_battery" for name in strategies):
                raise ValueError(
                    "The GUI-only no-battery execution path is not connected yet. "
                    "Select at least one battery strategy for this first CSV test."
                )

            battery = Battery(
                capacity_kWh=float(self.values["battery_capacity"].get()),
                energy_kWh=float(self.values["battery_initial_energy"].get()),
                max_charge_kw=float(self.values["battery_max_charge"].get()),
                max_discharge_kw=float(self.values["battery_max_discharge"].get()),
            )
            specification = MicrogridSpecification(
                battery=battery,
                pv_capacity_kw=float(self.values["pv_capacity"].get()),
                load_kw=float(self.values["load_power"].get()),
            )
            degradation_cost = float(self.values["degradation_cost"].get())
        except ValueError as error:
            messagebox.showerror("Invalid analysis setup", str(error), parent=self.window)
            return

        source_mode = str(self.values["source_mode"].get())
        self._update_analysis_details(
            source_mode=source_mode,
            timestep_minutes=timestep,
        )
        self.show_page("results")
        self.progress_message.set(
            "Loading CSV and running dispatch optimization..."
            if source_mode == "integrated_csv"
            else "Retrieving live price and carbon signals..."
        )
        self._set_analysis_message(
            "Analysis is running. The window will remain responsive."
        )
        self._clear_results_table()
        self.run_analysis_button.configure(state="disabled")
        self.analysis_started_at = time.perf_counter()
        self.elapsed_message.set("Elapsed time: 0.0 seconds")
        self.analysis_progress.configure(
            mode="determinate",
            maximum=100,
            value=2,
        )

        common_arguments = {
            "specification": specification,
            "start_date": str(self.values["start_date"].get()),
            "number_of_days": days,
            "timestep_minutes": timestep,
            "selected_scenarios": strategies,
            "carbon_weights": tuple(float(weight) for weight in weights),
            "degradation_cost_per_kWh": degradation_cost,
        }

        if source_mode == "integrated_csv":
            worker_kind = "integrated_csv"
            worker_arguments = {
                **common_arguments,
                "csv_path": str(self.values["signal_csv_path"].get()),
                "expected_timezone": str(self.values["timezone"].get()),
            }
        else:
            worker_kind = "live_api"
            price_mode = str(self.values["price_mode"].get())
            worker_arguments = {
                **common_arguments,
                "region_id": str(self.values["region_id"].get()),
                "market_provider": str(self.values["market_provider"].get()),
                "market_location": str(self.values["market_location"].get()),
                "carbon_provider": str(self.values["carbon_provider"].get()),
                "carbon_zone": str(self.values["carbon_zone"].get()),
                "timezone": str(self.values["timezone"].get()),
                "price_mode": price_mode,
                "fixed_retail_price": (
                    float(self.values["fixed_retail_price"].get())
                    if price_mode == "fixed_retail"
                    else None
                ),
                "price_csv_path": str(self.values["price_csv_path"].get()) or None,
            }

        self.analysis_process = self.process_context.Process(
            target=_run_csv_worker_process,
            args=(self.analysis_messages, worker_kind, worker_arguments),
            daemon=True,
        )
        self.analysis_process.start()
        self.worker_exit_empty_polls = 0
        self.window.after(100, self._poll_analysis_messages)

    def _update_analysis_details(
        self,
        *,
        source_mode: str,
        timestep_minutes: int,
    ) -> None:
        """Show the identifying settings for the current analysis run."""

        details = build_analysis_details(
            source_mode=source_mode,
            region_id=str(self.values["region_id"].get()),
            market_location=str(self.values["market_location"].get()),
            csv_path=str(self.values["signal_csv_path"].get()),
            start_date=str(self.values["start_date"].get()),
            end_date_inclusive=str(self.values["end_date_inclusive"].get()),
            timestep_minutes=timestep_minutes,
        )

        for label, value in details:
            self.analysis_detail_values[label].set(value)

    def _poll_analysis_messages(self) -> None:
        """Process a completed worker message without blocking Tkinter."""

        if self.is_closing:
            return

        if self.analysis_started_at is not None:
            elapsed = time.perf_counter() - self.analysis_started_at
            self.elapsed_message.set(
                f"Elapsed time: {format_runtime(elapsed)}"
            )

        try:
            status, payload = self.analysis_messages.get_nowait()
        except queue.Empty:
            if (
                self.analysis_process is not None
                and not self.analysis_process.is_alive()
            ):
                self.worker_exit_empty_polls += 1

                if self.worker_exit_empty_polls >= 10:
                    exit_code = self.analysis_process.exitcode
                    self.run_analysis_button.configure(state="normal")
                    elapsed = (
                        time.perf_counter() - self.analysis_started_at
                        if self.analysis_started_at is not None
                        else 0.0
                    )
                    self.analysis_started_at = None
                    self.elapsed_message.set(
                        f"Stopped after: {format_runtime(elapsed)}"
                    )
                    self.progress_message.set("Analysis worker stopped unexpectedly.")
                    self._set_analysis_message(
                        "The simulation worker exited without returning a result. "
                        f"Exit code: {exit_code}."
                    )
                    self._release_finished_analysis_process()
                    return

            self.window.after(100, self._poll_analysis_messages)
            return

        if status == "progress":
            progress_percent, progress_text = payload
            self.analysis_progress.configure(value=progress_percent)
            self.progress_message.set(
                f"{progress_text} ({progress_percent:.0f}%)"
            )
            self.window.after(100, self._poll_analysis_messages)
            return

        self.run_analysis_button.configure(state="normal")
        self._release_finished_analysis_process()

        elapsed = (
            time.perf_counter() - self.analysis_started_at
            if self.analysis_started_at is not None
            else 0.0
        )
        self.analysis_started_at = None

        if status == "error":
            self.elapsed_message.set(
                f"Stopped after: {format_runtime(elapsed)}"
            )
            self.progress_message.set("Analysis failed.")
            error_name, error_message = payload
            display_message = f"{error_name}: {error_message}"
            self._set_analysis_message(display_message)
            messagebox.showerror("Analysis failed", display_message, parent=self.window)
            return

        self.analysis_result = payload
        self.analysis_progress.configure(
            mode="determinate",
            maximum=100,
            value=100,
        )
        self.elapsed_message.set(
            f"Total runtime: {format_runtime(elapsed)}"
        )
        self.progress_message.set(
            f"Analysis complete: {len(payload.comparison)} scenario result(s)."
        )
        self._set_analysis_message(
            "Scroll horizontally to inspect every reported metric."
        )
        self._render_results_table(payload.comparison)

    def _release_finished_analysis_process(self) -> None:
        """Join and close a worker after it has returned its final message."""

        process = self.analysis_process

        if process is None:
            return

        process.join(timeout=1.0)

        if process.is_alive():
            return

        process.close()
        self.analysis_process = None

    def _close_application(self) -> None:
        """Release multiprocessing resources before destroying the window."""

        if self.is_closing:
            return

        self.is_closing = True
        process = self.analysis_process

        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2.0)
            if not process.is_alive():
                process.close()
            self.analysis_process = None

        self.analysis_messages.close()
        self.analysis_messages.join_thread()
        self.window.destroy()

    def _set_analysis_message(self, message: str) -> None:
        """Update the short message shown above the result table."""

        self.result_message.configure(text=message)

    def _clear_results_table(self) -> None:
        """Remove previously displayed table cells."""

        for child in self.table_frame.winfo_children():
            child.destroy()

        self.table_canvas.configure(height=100)

    def _render_results_table(self, comparison) -> None:
        """Display scenario metrics using bordered rows and columns."""

        self._clear_results_table()
        headings, rows = build_results_table(comparison)

        for column_index, heading in enumerate(headings):
            header = tk.Label(
                self.table_frame,
                text=heading,
                font=("Arial", 11, "bold"),
                background="#d9e3f0",
                relief="solid",
                borderwidth=1,
                padx=10,
                pady=8,
            )
            header.grid(
                row=0,
                column=column_index,
                sticky="nsew",
            )
            self._bind_result_table_scrolling(header)

        for row_index, row_values in enumerate(rows, start=1):
            background = "#ffffff" if row_index % 2 else "#f3f6f9"

            for column_index, value in enumerate(row_values):
                cell = tk.Label(
                    self.table_frame,
                    text=value,
                    font=("Arial", 11),
                    background=background,
                    relief="solid",
                    borderwidth=1,
                    padx=10,
                    pady=8,
                )
                cell.grid(
                    row=row_index,
                    column=column_index,
                    sticky="nsew",
                )
                self._bind_result_table_scrolling(cell)

        visible_height = min(48 + len(rows) * 38, 360)
        self.table_canvas.configure(height=visible_height)
        self.table_frame.update_idletasks()
        self._update_table_scroll_region()

    def _update_table_scroll_region(self, _event=None) -> None:
        """Keep both scroll directions aligned with the rendered table."""

        self.table_canvas.configure(
            scrollregion=self.table_canvas.bbox("all")
        )

    def _bind_result_table_scrolling(self, widget) -> None:
        """Enable mouse and trackpad scrolling over table content."""

        widget.bind(
            "<MouseWheel>",
            self._scroll_result_table_vertical,
        )
        widget.bind(
            "<Shift-MouseWheel>",
            self._scroll_result_table_horizontal,
        )

    def _scroll_result_table_vertical(self, event):
        """Move through scenario rows with a wheel or vertical swipe."""

        if event.delta:
            direction = -1 if event.delta > 0 else 1
            self.table_canvas.yview_scroll(direction, "units")
        return "break"

    def _scroll_result_table_horizontal(self, event):
        """Move through metric columns with Shift-wheel or horizontal swipe."""

        if event.delta:
            direction = -1 if event.delta > 0 else 1
            self.table_canvas.xview_scroll(direction, "units")
        return "break"

def _run_csv_worker_process(
    message_queue,
    worker_kind: str,
    arguments: dict,
) -> None:
    """Run data retrieval and OpenDSS in an isolated worker process."""

    try:
        requested_weights = arguments.get("carbon_weights", ())
        selected_scenarios = arguments.get("selected_scenarios", ())
        analysis_set_count = (
            len(requested_weights)
            if "combined_optimal" in selected_scenarios
            else 1
        )
        setup_step_count = 1 if worker_kind == "integrated_csv" else 2
        total_progress_steps = setup_step_count + 4 * analysis_set_count
        completed_progress_steps = 0

        def report_progress(message: str) -> None:
            nonlocal completed_progress_steps
            completed_progress_steps += 1
            progress_percent = calculate_progress_percentage(
                completed_progress_steps,
                total_progress_steps,
            )
            message_queue.put(
                (
                    "progress",
                    (progress_percent, message),
                )
            )

        arguments = {
            **arguments,
            "progress_callback": report_progress,
        }
        if worker_kind == "integrated_csv":
            result = run_integrated_csv_analysis(**arguments)
        elif worker_kind == "live_api":
            result = run_live_api_analysis(**arguments)
        else:
            raise ValueError(f"Unknown analysis worker kind: {worker_kind}.")
    except Exception as error:
        message_queue.put(
            (
                "error",
                (type(error).__name__, str(error)),
            )
        )
    else:
        message_queue.put(("success", result))


def format_runtime(elapsed_seconds: float) -> str:
    """Format an elapsed duration for the results screen."""

    elapsed_seconds = max(float(elapsed_seconds), 0.0)

    if elapsed_seconds < 60:
        return f"{elapsed_seconds:.1f} seconds"

    minutes, seconds = divmod(elapsed_seconds, 60)

    if minutes < 60:
        return f"{int(minutes)} min {seconds:.1f} sec"

    hours, minutes = divmod(int(minutes), 60)
    return f"{hours} hr {minutes} min {seconds:.1f} sec"


def calculate_progress_percentage(
    completed_steps: int,
    total_steps: int,
) -> float:
    """Map completed backend milestones onto a 5–95% progress range."""

    if total_steps <= 0:
        return 5.0

    bounded_steps = min(max(completed_steps, 0), total_steps)
    return 5.0 + 90.0 * bounded_steps / total_steps


def selected_strategies(strategy_values: dict[str, object]) -> tuple[str, ...]:
    """Return selected strategies in stable display order."""

    return tuple(
        name
        for name in STRATEGY_LABELS
        if bool(strategy_values[name].get())
    )


def build_review_rows(
    *,
    source_mode: str,
    region_id: str,
    start_date: str,
    end_date_inclusive: str,
    timestep_minutes: str,
    price_mode: str,
    strategies: tuple[str, ...],
    carbon_weights: tuple[str, ...],
    degradation_cost: str,
    battery_active: bool,
    battery_capacity: str,
    battery_initial_energy: str,
    battery_max_charge: str,
    battery_max_discharge: str,
    pv_capacity: str,
    load_power: str,
) -> tuple[tuple[str, str, str], ...]:
    """Build the rows shown in the Step 3 review table."""

    source_label = "Live APIs" if source_mode == "live_api" else "Integrated CSV"
    region_label = region_id if source_mode == "live_api" else "Not applicable"
    price_label = (
        PRICE_MODE_LABELS[price_mode]
        if source_mode == "live_api"
        else "Included in integrated CSV"
    )
    battery_value = "Active" if battery_active else "Ignored"

    return (
        ("Analysis", "Data source", source_label),
        ("Analysis", "Region", region_label),
        ("Analysis", "Start date", start_date),
        ("Analysis", "End date (inclusive)", end_date_inclusive),
        ("Analysis", "Time interval", f"{timestep_minutes} minutes"),
        ("Analysis", "Electricity price", price_label),
        ("Strategies", "Selected scenarios", ", ".join(strategies)),
        ("Strategies", "Combined carbon weights", ", ".join(carbon_weights)),
        (
            "Strategies",
            "Battery degradation cost",
            f"{degradation_cost} $/kWh throughput",
        ),
        ("Microgrid", "Battery", battery_value),
        (
            "Microgrid",
            "Battery capacity",
            f"{battery_capacity} kWh" if battery_active else "Ignored",
        ),
        (
            "Microgrid",
            "Initial battery energy",
            f"{battery_initial_energy} kWh" if battery_active else "Ignored",
        ),
        (
            "Microgrid",
            "Maximum charging power",
            f"{battery_max_charge} kW" if battery_active else "Ignored",
        ),
        (
            "Microgrid",
            "Maximum discharging power",
            f"{battery_max_discharge} kW" if battery_active else "Ignored",
        ),
        ("Microgrid", "PV capacity", f"{pv_capacity} kW"),
        ("Microgrid", "Load assumption", f"{load_power} kW"),
    )


def calculate_inclusive_day_count(
    start_date: str,
    end_date_inclusive: str,
) -> int:
    """Return the number of calendar days when both boundaries are included."""

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date_inclusive)
    except (TypeError, ValueError) as error:
        raise ValueError("Start and end dates must use YYYY-MM-DD format.") from error

    if end < start:
        raise ValueError("Inclusive end date must not precede the start date.")

    return (end - start).days + 1


def parse_carbon_weights(
    mode: str,
    *,
    single: str,
    explicit_list: str,
    range_start: str,
    range_end: str,
    range_interval: str,
) -> list[Decimal]:
    """Parse one, several, or an inclusive range of carbon weights."""

    try:
        if mode == "single":
            values = [Decimal(single)]
        elif mode == "list":
            values = [Decimal(value.strip()) for value in explicit_list.split(",") if value.strip()]
        elif mode == "range":
            start = Decimal(range_start)
            end = Decimal(range_end)
            interval = Decimal(range_interval)
            if interval <= 0:
                raise ValueError("Carbon-weight range interval must be positive.")
            if end < start:
                raise ValueError("Carbon-weight range end must not precede its start.")
            span = end - start
            if span % interval != 0:
                raise ValueError("Carbon-weight interval must land exactly on the inclusive end value.")
            count = int(span / interval)
            values = [start + interval * index for index in range(count + 1)]
        else:
            raise ValueError(f"Unknown carbon-weight mode: {mode}.")
    except InvalidOperation as error:
        raise ValueError("Carbon weights must be valid numbers.") from error

    if not values:
        raise ValueError("Provide at least one carbon weight.")
    if any(value < 0 for value in values):
        raise ValueError("Carbon weights must not be negative.")
    if len(set(values)) != len(values):
        raise ValueError("Carbon weights must not contain duplicates.")
    return values


def create_guided_application_window() -> tk.Tk:
    """Create the main guided microgrid-analysis window."""

    window = tk.Tk()
    MicrogridApplication(window)
    return window
