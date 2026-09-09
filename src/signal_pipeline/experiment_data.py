from dataclasses import dataclass
import pandas as pd

@dataclass
class ExperimentData:
    synthetic_data: pd.DataFrame
    price_data: pd.DataFrame
    carbon_data: pd.DataFrame
    real_market_data: pd.DataFrame