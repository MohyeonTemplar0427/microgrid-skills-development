"""PG&E tariff definitions.

Rates below are transcribed from PG&E's published tariff book and are valid
for the stated effective date only. They are **versioned data**: when PG&E
files new rates, add a new :class:`TariffDefinition` with its own effective
window rather than editing these numbers in place, so historical analyses stay
reproducible.
"""

from datetime import date

from .tariffs import (
    CustomerClass,
    DemandChargeBasis,
    DemandChargeComponent,
    ExportCompensationRule,
    Season,
    SeasonDefinition,
    ServiceType,
    ServiceVoltageClass,
    TOUPeriod,
    TariffDefinition,
    register_tariff,
)

B10_SOURCE_URL = (
    "https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_B-10.pdf"
)

# Summer is June 1 through September 30; winter is October 1 through May 31.
PGE_SEASONS = SeasonDefinition(summer_months=frozenset({6, 7, 8, 9}))

PGE_B10_SECONDARY_BUNDLED = register_tariff(
    TariffDefinition(
        tariff_id="pge_b10_secondary_bundled_2026_03_01",
        name="PG&E B-10 Medium General Demand-Metered Service",
        utility="Pacific Gas and Electric",
        effective_start=date(2026, 3, 1),
        service_voltage_class=ServiceVoltageClass.SECONDARY,
        customer_class=CustomerClass.COMMERCIAL,
        service_type=ServiceType.BUNDLED,
        season_definition=PGE_SEASONS,
        # $ per meter per day.
        daily_customer_charge=11.36882,
        demand_charges=(
            DemandChargeComponent(
                name="maximum_demand",
                rate_per_kW=20.50,
                basis=DemandChargeBasis.MAXIMUM,
            ),
        ),
        tou_periods=(
            # --- Summer: June 1 - September 30 ---
            TOUPeriod(
                name="summer_peak",
                rate_per_kWh=0.33947,
                start_hour=16,
                end_hour=21,
                season=Season.SUMMER,
                priority=30,
            ),
            TOUPeriod(
                name="summer_part_peak_afternoon",
                rate_per_kWh=0.27778,
                start_hour=14,
                end_hour=16,
                season=Season.SUMMER,
                priority=20,
            ),
            TOUPeriod(
                name="summer_part_peak_evening",
                rate_per_kWh=0.27778,
                start_hour=21,
                end_hour=23,
                season=Season.SUMMER,
                priority=20,
            ),
            TOUPeriod(
                name="summer_off_peak",
                rate_per_kWh=0.24522,
                start_hour=0,
                end_hour=0,  # full day, lowest priority
                season=Season.SUMMER,
                priority=0,
            ),
            # --- Winter: October 1 - May 31 ---
            TOUPeriod(
                name="winter_peak",
                rate_per_kWh=0.26321,
                start_hour=16,
                end_hour=21,
                season=Season.WINTER,
                priority=30,
            ),
            # Super off-peak applies only in March, April and May.
            TOUPeriod(
                name="winter_super_off_peak",
                rate_per_kWh=0.19139,
                start_hour=9,
                end_hour=14,
                season=Season.WINTER,
                months=frozenset({3, 4, 5}),
                priority=20,
            ),
            TOUPeriod(
                name="winter_off_peak",
                rate_per_kWh=0.22773,
                start_hour=0,
                end_hour=0,  # full day, lowest priority
                season=Season.WINTER,
                priority=0,
            ),
        ),
        export_rule=ExportCompensationRule(
            name="not_modelled",
            implemented=False,
            note=(
                "B-10 export compensation (NEM or the Net Billing Tariff) is "
                "not modelled. Configure an explicit fixed or CSV export "
                "price in the surplus configuration instead."
            ),
        ),
        source_url=B10_SOURCE_URL,
        version="2026-03-01",
        notes=(
            "Secondary voltage means service below 2,400 V, which includes "
            "the modelled 480 V service. Rates are bundled (PG&E supplies "
            "generation); CCA and Direct Access customers pay different "
            "generation components and are not modelled."
        ),
    )
)


# B-19 is deliberately NOT registered. It carries several distinct demand
# components -- maximum demand plus separate time-related peak and part-peak
# demand charges -- and approximating it with B-10's single maximum-demand
# charge would understate cost in a way that looks plausible. Implementing it
# requires DemandChargeBasis.PEAK_PERIOD and PART_PEAK_PERIOD to be computed
# per TOU window, which charges.py supports structurally but has not been
# validated against a published B-19 bill.
B19_NOT_IMPLEMENTED_NOTE = (
    "PG&E B-19 is not implemented. It uses multiple demand-charge components "
    "(maximum, peak-period and part-peak-period demand) that cannot be "
    "approximated by B-10's single maximum-demand charge without materially "
    "misstating cost."
)


def default_commercial_tariff() -> TariffDefinition:
    return PGE_B10_SECONDARY_BUNDLED
