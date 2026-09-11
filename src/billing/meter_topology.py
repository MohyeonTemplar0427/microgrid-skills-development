"""Metering and billing topology.

This layer is **separate from the physical OpenDSS network**, and the
separation is deliberate:

* OpenDSS decides voltages, currents, losses and the real power at the PCC.
* Meter topology decides which flows are *billed together*.
* Tariffs decide the rates.
* :mod:`src.billing.charges` computes the money.

Two sites with identical physics can have very different bills purely because
of how meters are arranged, which is why this cannot be inferred from the
network model.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class MeterTopologyMode(StrEnum):
    SINGLE_PCC = "single_pcc"
    MASTER_WITH_SUBMETERS = "master_with_submeters"
    INDIVIDUAL_METERS = "individual_meters"
    INDIVIDUAL_WITH_SHARED_GENERATION = "individual_with_shared_generation"


class ConnectionLocation(StrEnum):
    """Where a physical asset attaches in the billing topology."""

    SHARED_PCC = "shared_pcc"
    MASTER_METER = "master_meter"
    COMMON_AREA_METER = "common_area_meter"
    INDIVIDUAL_METER = "individual_meter"


class MeterTopologyError(ValueError):
    pass


# Allocation percentages must sum to 100% within this tolerance.
ALLOCATION_TOLERANCE_PERCENT = 1e-6


@dataclass
class UtilityMeter:
    """One billable meter.

    ``is_utility_account`` distinguishes a real utility account, which incurs
    a customer charge and a demand charge, from an internal submeter used only
    to allocate a shared bill.
    """

    meter_id: str
    tariff_id: str | None = None
    is_utility_account: bool = True
    is_common_area: bool = False
    allocation_percent: float | None = None

    def __post_init__(self) -> None:
        if not str(self.meter_id).strip():
            raise MeterTopologyError("Meter id must not be empty.")

        if self.allocation_percent is not None:
            if not 0 <= self.allocation_percent <= 100:
                raise MeterTopologyError(
                    f"Meter {self.meter_id!r} allocation percent must be "
                    f"within 0..100; received {self.allocation_percent}."
                )


@dataclass
class MeterTopology:
    """The complete billing arrangement for one site."""

    mode: MeterTopologyMode = MeterTopologyMode.SINGLE_PCC
    meters: tuple[UtilityMeter, ...] = ()
    default_tariff_id: str | None = None
    battery_location: ConnectionLocation = ConnectionLocation.SHARED_PCC
    battery_meter_id: str | None = None
    pv_location: ConnectionLocation = ConnectionLocation.SHARED_PCC
    pv_meter_id: str | None = None
    has_common_area_meter: bool = False
    uses_equal_allocation_approximation: bool = False
    approximation_warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.mode = MeterTopologyMode(self.mode)
        self.battery_location = ConnectionLocation(self.battery_location)
        self.pv_location = ConnectionLocation(self.pv_location)

        if not self.meters:
            raise MeterTopologyError(
                "A meter topology needs at least one meter."
            )

        identifiers = [meter.meter_id for meter in self.meters]

        if len(set(identifiers)) != len(identifiers):
            raise MeterTopologyError(
                f"Meter ids must be unique; received {identifiers}."
            )

        self._validate_mode()
        self._validate_connection_locations()

    def _validate_mode(self) -> None:
        accounts = self.utility_accounts

        if self.mode == MeterTopologyMode.SINGLE_PCC:
            if len(accounts) != 1:
                raise MeterTopologyError(
                    f"Single-PCC topology must have exactly one utility "
                    f"account; found {len(accounts)}."
                )

        elif self.mode == MeterTopologyMode.MASTER_WITH_SUBMETERS:
            if len(accounts) != 1:
                raise MeterTopologyError(
                    f"Master-meter topology bills one utility account; found "
                    f"{len(accounts)}. Submeters must have "
                    f"is_utility_account=False, since they allocate an "
                    f"internal share rather than incurring their own utility "
                    f"charges."
                )

            if len(self.meters) < 2:
                raise MeterTopologyError(
                    "Master-meter topology needs at least one submeter."
                )

        elif self.mode == MeterTopologyMode.INDIVIDUAL_METERS:
            if len(accounts) < 2:
                raise MeterTopologyError(
                    f"Individually metered topology needs at least two "
                    f"utility accounts; found {len(accounts)}."
                )

        elif self.mode == (
            MeterTopologyMode.INDIVIDUAL_WITH_SHARED_GENERATION
        ):
            if len(accounts) < 2:
                raise MeterTopologyError(
                    "Shared-generation topology needs at least two utility "
                    "accounts."
                )

            self._validate_allocation()

    def _validate_allocation(self) -> None:
        allocated = [
            meter
            for meter in self.meters
            if meter.allocation_percent is not None
        ]

        if not allocated:
            raise MeterTopologyError(
                "Shared-generation topology requires allocation percentages "
                "on the meters receiving generation credit."
            )

        total = sum(meter.allocation_percent for meter in allocated)

        if abs(total - 100.0) > ALLOCATION_TOLERANCE_PERCENT:
            raise MeterTopologyError(
                f"Shared-generation allocation percentages must sum to 100%; "
                f"they sum to {total}. Adjust the allocation so every "
                f"generated kWh is credited exactly once."
            )

    def _validate_connection_locations(self) -> None:
        for label, location, meter_id in (
            ("Battery", self.battery_location, self.battery_meter_id),
            ("PV", self.pv_location, self.pv_meter_id),
        ):
            if location == ConnectionLocation.INDIVIDUAL_METER:
                if meter_id is None:
                    raise MeterTopologyError(
                        f"{label} is connected to an individual meter, so a "
                        f"meter id must be given."
                    )

                if meter_id not in {m.meter_id for m in self.meters}:
                    raise MeterTopologyError(
                        f"{label} meter {meter_id!r} is not in the topology. "
                        f"Known meters: "
                        f"{sorted(m.meter_id for m in self.meters)}."
                    )

            if location == ConnectionLocation.COMMON_AREA_METER:
                if not any(m.is_common_area for m in self.meters):
                    raise MeterTopologyError(
                        f"{label} is connected to the common-area meter, but "
                        f"the topology has no common-area meter."
                    )

    @property
    def utility_accounts(self) -> tuple[UtilityMeter, ...]:
        """Meters that incur customer and demand charges."""

        return tuple(
            meter for meter in self.meters if meter.is_utility_account
        )

    @property
    def utility_account_count(self) -> int:
        return len(self.utility_accounts)

    @property
    def submeters(self) -> tuple[UtilityMeter, ...]:
        return tuple(
            meter for meter in self.meters if not meter.is_utility_account
        )

    @property
    def demand_is_aggregate(self) -> bool:
        """True when demand is measured on the combined PCC/master flow."""

        return self.mode in (
            MeterTopologyMode.SINGLE_PCC,
            MeterTopologyMode.MASTER_WITH_SUBMETERS,
        )

    def tariff_for(self, meter: UtilityMeter) -> str:
        tariff_id = meter.tariff_id or self.default_tariff_id

        if tariff_id is None:
            raise MeterTopologyError(
                f"Meter {meter.meter_id!r} has no tariff, and the topology "
                f"has no default. Assign a tariff per meter: a commercial "
                f"demand-metered schedule must not be applied to residential "
                f"unit meters."
            )

        return tariff_id

    def describe(self) -> str:
        parts = [
            f"{self.mode.value}",
            f"{self.utility_account_count} utility account(s)",
        ]

        if self.submeters:
            parts.append(f"{len(self.submeters)} submeter(s)")

        if self.has_common_area_meter:
            parts.append("common-area meter")

        parts.append(f"battery at {self.battery_location.value}")
        parts.append(f"PV at {self.pv_location.value}")

        return "; ".join(parts)


def single_pcc_topology(tariff_id: str) -> MeterTopology:
    """The default: one utility meter at the point of common coupling."""

    return MeterTopology(
        mode=MeterTopologyMode.SINGLE_PCC,
        meters=(UtilityMeter(meter_id="pcc", tariff_id=tariff_id),),
        default_tariff_id=tariff_id,
    )


def master_with_submeters_topology(
    tariff_id: str,
    submeter_count: int,
) -> MeterTopology:
    """One utility bill at a master meter, submeters for allocation only."""

    if submeter_count < 1:
        raise MeterTopologyError(
            "Master-meter topology needs at least one submeter."
        )

    meters = [UtilityMeter(meter_id="master", tariff_id=tariff_id)]
    meters += [
        UtilityMeter(
            meter_id=f"unit_{number}",
            is_utility_account=False,
        )
        for number in range(1, submeter_count + 1)
    ]

    return MeterTopology(
        mode=MeterTopologyMode.MASTER_WITH_SUBMETERS,
        meters=tuple(meters),
        default_tariff_id=tariff_id,
    )


def individual_meters_topology(
    unit_tariff_id: str,
    unit_count: int,
    *,
    common_area_tariff_id: str | None = None,
    uses_equal_allocation_approximation: bool = False,
) -> MeterTopology:
    """Separately billed units, each its own utility account.

    When per-unit load profiles are unavailable, the caller may opt into an
    equal-allocation approximation. That choice is recorded as a warning so it
    is surfaced in Review and Run and in the results, never applied silently.
    """

    if unit_count < 2:
        raise MeterTopologyError(
            "Individually metered topology needs at least two units."
        )

    meters = [
        UtilityMeter(meter_id=f"unit_{number}", tariff_id=unit_tariff_id)
        for number in range(1, unit_count + 1)
    ]

    if common_area_tariff_id is not None:
        meters.append(
            UtilityMeter(
                meter_id="common_area",
                tariff_id=common_area_tariff_id,
                is_common_area=True,
            )
        )

    warnings = ()

    if uses_equal_allocation_approximation:
        warnings = (
            f"APPROXIMATION: site load is split equally across "
            f"{unit_count} units because per-unit profiles were not "
            f"supplied. Real units differ, so per-meter demand charges and "
            f"any tiered energy charges are approximate.",
        )

    return MeterTopology(
        mode=MeterTopologyMode.INDIVIDUAL_METERS,
        meters=tuple(meters),
        default_tariff_id=unit_tariff_id,
        has_common_area_meter=common_area_tariff_id is not None,
        uses_equal_allocation_approximation=(
            uses_equal_allocation_approximation
        ),
        approximation_warnings=warnings,
    )


def shared_generation_topology(
    unit_tariff_id: str,
    unit_count: int,
    allocation_percentages: dict[str, float],
    *,
    common_area_tariff_id: str | None = None,
    generation_tariff_id: str | None = None,
) -> MeterTopology:
    """Individually metered units plus a separately metered shared generator.

    Allocation is a **billing credit**, not a claim that specified physical
    electrons reached a particular unit. Percentages must sum to 100% so every
    generated kWh is credited exactly once.
    """

    meters = [
        UtilityMeter(
            meter_id=f"unit_{number}",
            tariff_id=unit_tariff_id,
            allocation_percent=allocation_percentages.get(f"unit_{number}"),
        )
        for number in range(1, unit_count + 1)
    ]

    if common_area_tariff_id is not None:
        meters.append(
            UtilityMeter(
                meter_id="common_area",
                tariff_id=common_area_tariff_id,
                is_common_area=True,
                allocation_percent=allocation_percentages.get("common_area"),
            )
        )

    meters.append(
        UtilityMeter(
            meter_id="shared_generation",
            tariff_id=generation_tariff_id or unit_tariff_id,
            is_utility_account=True,
        )
    )

    return MeterTopology(
        mode=MeterTopologyMode.INDIVIDUAL_WITH_SHARED_GENERATION,
        meters=tuple(meters),
        default_tariff_id=unit_tariff_id,
        has_common_area_meter=common_area_tariff_id is not None,
        approximation_warnings=(
            "Shared-generation allocation is a billing credit. It does not "
            "assert that specific physical electrons served a specific unit.",
        ),
    )
